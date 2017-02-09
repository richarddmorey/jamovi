#
# Copyright (C) 2016 Jonathon Love
#

import os
import os.path
import platform

from ..core import MeasureType
from ..core import Dirs
from ..core import MemoryMap
from ..core import DataSet

from .settings import Settings

from . import jamovi_pb2 as jcoms

from .utils import conf
from .enginemanager import EngineManager
from .analyses import Analyses
from .modules import Modules
from . import formatio

import uuid
import posixpath
import math
import yaml
import logging
import time

import threading
from threading import Thread

from .utils import fs

log = logging.getLogger('jamovi')


class InstanceData:
    def __init__(self):
        self.analyses = None
        self.dataset = None
        self.title = None
        self.path = ''


class Instance:

    instances = { }
    _garbage_collector = None

    @staticmethod
    def get(instance_id):
        return Instance.instances.get(instance_id)

    class GarbageCollector:

        def __init__(self):
            self._stopped = False
            self._thread = Thread(target=self.run)
            self._thread.start()

        def run(self):
            parent = threading.main_thread()

            while True:
                time.sleep(.3)
                if self._stopped is True:
                    break
                if parent.is_alive() is False:
                    break
                for id, instance in Instance.instances.items():
                    if instance.inactive_for > 2:
                        log.info('cleaning up: ' + str(id))
                        instance.close()
                        del Instance.instances[id]
                        break

        def stop(self):
            self._stopped = True

    def _normalise_path(path):
        nor_path = path
        if path.startswith('{{Documents}}'):
            nor_path = path.replace('{{Documents}}', Dirs.documents_dir())
        elif path.startswith('{{Desktop}}'):
            nor_path = path.replace('{{Desktop}}', Dirs.desktop_dir())
        elif path.startswith('{{Home}}'):
            nor_path = path.replace('{{Home}}', Dirs.home_dir())
        elif path.startswith('{{Examples}}'):
            nor_path = path.replace('{{Examples}}', conf.get('examples_path'))
        return nor_path

    def _virtualise_path(path):
        documents_dir = Dirs.documents_dir()
        home_dir = Dirs.home_dir()
        desktop_dir = Dirs.desktop_dir()

        vir_path = path
        if path.startswith(documents_dir):
            vir_path = path.replace(documents_dir, '{{Documents}}')
        elif path.startswith(desktop_dir):
            vir_path = path.replace(desktop_dir, '{{Desktop}}')
        elif path.startswith(home_dir):
            vir_path = path.replace(home_dir, '{{Home}}')

        return vir_path

    def __init__(self, session_path, instance_id=None):

        if Instance._garbage_collector is None:
            Instance._garbage_collector = Instance.GarbageCollector()

        self._session_path = session_path
        if instance_id is None:
            instance_id = str(uuid.uuid4())
        self._instance_id = instance_id

        self._mm = None
        self._data = InstanceData()
        self._data.dataset = None
        self._data.analyses = Analyses()

        self._coms = None
        self._em = EngineManager(self._instance_id, self._data.analyses, session_path)
        self._inactive_since = None

        self._data.analyses.add_results_changed_listener(self._on_results)
        self._em.add_engine_listener(self._on_engine_event)

        settings = Settings.retrieve()
        settings.sync()

        self._data.instance_path = os.path.join(self._session_path, self._instance_id)
        os.makedirs(self._data.instance_path, exist_ok=True)
        self._buffer_path = os.path.join(self._data.instance_path, 'buffer')

        self._em.start()

        Instance.instances[self._instance_id] = self

    @property
    def id(self):
        return self._instance_id

    def set_coms(self, coms):
        if self._coms is not None:
            self._coms.remove_close_listener(self._close)
        self._coms = coms
        self._coms.add_close_listener(self._close)
        self._inactive_since = None

    def close(self):
        if self._mm is not None:
            self._mm.close()
        self._em.stop()

    def _close(self):
        self._coms.remove_close_listener(self._close)
        self._coms = None
        self._inactive_since = time.time()

    @property
    def is_active(self):
        return self._coms is not None

    @property
    def inactive_for(self):
        if self._inactive_since is None:
            return 0
        else:
            return time.time() - self._inactive_since

    @property
    def analyses(self):
        return self._data.analyses

    def get_path_to_resource(self, resourceId):
        return os.path.join(self._data.instance_path, resourceId)

    def on_request(self, request):
        if type(request) == jcoms.DataSetRR:
            self._on_dataset(request)
        elif type(request) == jcoms.OpenRequest:
            self._on_open(request)
        elif type(request) == jcoms.SaveRequest:
            self._on_save(request)
        elif type(request) == jcoms.InfoRequest:
            self._on_info(request)
        elif type(request) == jcoms.SettingsRequest:
            self._on_settings(request)
        elif type(request) == jcoms.AnalysisRequest:
            self._on_analysis(request)
        elif type(request) == jcoms.FSRequest:
            self._on_fs_request(request)
        elif type(request) == jcoms.ModuleRequest:
            self._on_module(request)
        elif type(request) == jcoms.StoreRequest:
            self._on_store(request)
        else:
            log.info('unrecognised request')
            log.info(request.payloadType)

    def _on_results(self, analysis):
        if self._coms is not None:
            self._coms.send(analysis.results, self._instance_id)

    def _on_fs_request(self, request):
        path = request.path
        location = path

        path = Instance._normalise_path(path)

        response = jcoms.FSResponse()
        if path.startswith('{{Root}}'):

            entry = response.contents.add()
            entry.name = 'Documents'
            entry.path = '{{Documents}}'
            entry.type = jcoms.FSEntry.Type.Value('SPECIAL_FOLDER')

            entry = response.contents.add()
            entry.name = 'Desktop'
            entry.path = '{{Desktop}}'
            entry.type = jcoms.FSEntry.Type.Value('SPECIAL_FOLDER')

            entry = response.contents.add()
            entry.name = 'Home'
            entry.path = '{{Home}}'
            entry.type = jcoms.FSEntry.Type.Value('SPECIAL_FOLDER')

            if platform.uname().system == 'Windows':
                for drive_letter in range(ord('A'), ord('Z') + 1):
                    drive = chr(drive_letter) + ':'
                    if os.path.exists(drive):
                        entry = response.contents.add()
                        entry.name = drive
                        entry.path = drive
                        entry.type = jcoms.FSEntry.Type.Value('DRIVE')

            self._coms.send(response, self._instance_id, request)

        else:
            try:
                for direntry in os.scandir(path + '/'):  # add a / in case we get C:
                    if fs.is_hidden(direntry.path):
                        show = False
                    elif direntry.is_dir():
                        entry_type = jcoms.FSEntry.Type.Value('FOLDER')
                        if fs.is_link(direntry.path):
                            show = False
                        else:
                            show = True
                    else:
                        entry_type = jcoms.FSEntry.Type.Value('FILE')
                        show = formatio.is_supported(direntry.name)

                    if show:
                        entry = response.contents.add()
                        entry.name = direntry.name
                        entry.type = entry_type
                        entry.path = posixpath.join(location, direntry.name)

                self._coms.send(response, self._instance_id, request)

            except OSError as e:
                base    = os.path.basename(path)
                message = 'Unable to open {}'.format(base)
                cause = e.strerror
                self._coms.send_error(message, cause, self._instance_id, request)

    def _on_save(self, request):
        path = request.filename
        path = Instance._normalise_path(path)

        try:
            file_exists = os.path.isfile(path)
            success = False
            if file_exists is False or request.overwrite is True:
                formatio.write(self._data, path)
                success = True
                self._data.dataset.is_edited = False

            response = jcoms.SaveProgress()
            response.fileExists = file_exists
            response.success = success
            self._coms.send(response, self._instance_id, request)

            if success:
                self._add_to_recents(path)

        except OSError as e:
            base    = os.path.basename(path)
            message = 'Unable to save {}'.format(base)
            cause = e.strerror
            self._coms.send_error(message, cause, self._instance_id, request)

        except Exception as e:
            base    = os.path.basename(path)
            message = 'Unable to save {}'.format(base)
            cause = str(e)
            self._coms.send_error(message, cause, self._instance_id, request)

    def _on_open(self, request):
        path = request.filename
        nor_path = Instance._normalise_path(path)

        self._mm = MemoryMap.create(self._buffer_path, 65536)
        dataset = DataSet.create(self._mm)

        try:
            self._data.dataset = dataset

            is_example = path.startswith('{{Examples}}')
            formatio.read(self._data, nor_path, is_example)
            self._coms.send(None, self._instance_id, request)

            if path != '' and not is_example:
                self._add_to_recents(path)

        except OSError as e:
            base    = os.path.basename(path)
            message = 'Unable to open {}'.format(base)
            cause = e.strerror
            self._coms.send_error(message, cause, self._instance_id, request)

        except Exception as e:
            base    = os.path.basename(path)
            message = 'Unable to open {}'.format(base)
            cause = str(e)
            self._coms.send_error(message, cause, self._instance_id, request)

    def _open_callback(self, task, progress):
        response = jcoms.ComsMessage()
        response.open.status = jcoms.Status.Value('IN_PROGRESS')
        response.open.progress = progress
        response.open.progress_task = task

        self._coms.send(response, self._instance_id)

    def rerun(self):
        self._em.restart_engines()

    def _on_analysis(self, request):

        if request.restartEngines:

            self.rerun()

        elif request.HasField('options'):

            analysis = self._data.analyses.get(request.analysisId)
            if analysis is not None:
                self._data.dataset.is_edited = True
                if request.perform is jcoms.AnalysisRequest.Perform.Value('DELETE'):
                    del self._data.analyses[request.analysisId]
                else:
                    analysis.set_options(request.options, request.changed)
            else:
                log.error('Instance._on_analysis(): Analysis ' + analysis.id + ' could not be found')

            self._coms.discard(request)

        else:
            try:
                analysis = self._data.analyses.create(request.analysisId, request.name, request.ns)
                self._data.dataset.is_edited = True

                response = jcoms.AnalysisResponse()
                response.analysisId = request.analysisId
                response.options.ParseFromString(analysis.options.as_bytes())
                response.status = jcoms.AnalysisStatus.Value('ANALYSIS_NONE')

                self._coms.send(response, self._instance_id, request, False)

            except OSError as e:

                log.error('Could not create analysis: ' + str(e))

                response = jcoms.AnalysisResponse()
                response.analysisId = request.analysisId
                response.status = jcoms.AnalysisStatus.Value('ANALYSIS_ERROR')
                response.error.message = 'Could not create analysis: ' + str(e)

                self._coms.send(response, self._instance_id, request, True)

    def _on_info(self, request):

        response = jcoms.InfoResponse()

        has_dataset = self._data.dataset is not None
        response.hasDataSet = has_dataset

        if has_dataset:
            response.title = self._data.title
            response.path = self._data.path
            response.rowCount = self._data.dataset.row_count
            response.columnCount = self._data.dataset.column_count
            response.edited = self._data.dataset.is_edited
            response.blank = self._data.dataset.is_blank

            for column in self._data.dataset:
                column_schema = response.schema.columns.add()
                self._populate_column_schema(column, column_schema)

        for analysis in self._data.analyses:
            if analysis.has_results:
                analysis_pb = response.analyses.add()
                analysis_pb.CopyFrom(analysis.results)

        self._coms.send(response, self._instance_id, request)

    def _on_dataset(self, request):

        if self._data.dataset is None:
            return

        response = jcoms.DataSetRR()

        response.op = request.op
        response.rowStart    = request.rowStart
        response.columnStart = request.columnStart
        response.rowEnd      = request.rowEnd
        response.columnEnd   = request.columnEnd

        if request.op == jcoms.GetSet.Value('SET'):
            self._on_dataset_set(request, response)
        else:
            self._on_dataset_get(request, response)

        self._coms.send(response, self._instance_id, request)

    def _on_module(self, request):

        modules = Modules.instance()

        if request.command == jcoms.ModuleRequest.ModuleCommand.Value('INSTALL'):
            modules.install(
                request.path,
                lambda t, result: self._on_module_callback(t, result, request))
        elif request.command == jcoms.ModuleRequest.ModuleCommand.Value('UNINSTALL'):
            try:
                modules.uninstall(request.name)
                self._coms.send(None, self._instance_id, request)
                self._notify_modules_changed()
            except Exception as e:
                log.exception(e)
                self._coms.send_error(str(e), None, self._instance_id, request)

    def _on_module_callback(self, t, result, request):
        if t == 'progress':
            progress = jcoms.Progress()
            progress.progress = result[0]
            progress.total = result[1]
            self._coms.send(progress, self._instance_id, request, complete=False)
        elif t == 'error':
            self._coms.send_error('Unable to install module', str(result), self._instance_id, request)
        elif t == 'success':
            self._coms.send(None, self._instance_id, request)
            self._notify_modules_changed()
        else:
            log.error("Instance._on_module_callback(): shouldn't get here")

    def _on_module_install_error(self, request, e):
        log.error(str(e))
        self._coms.send_error(str(e), None, self._instance_id, request)

    def _on_module_install_progress(self, request, progress):
        print(progress)

    def _on_store(self, request):
        modules = Modules.instance()
        modules.read_store(lambda t, res: self._on_store_callback(request, t, res))

    def _on_store_callback(self, request, t, result):
        if t == 'progress':
            progress = jcoms.Progress()
            progress.progress = result[0]
            progress.total = result[1]
            self._coms.send(progress, self._instance_id, request, complete=False)
        elif t == 'error':
            self._coms.send_error('Unable to access store', str(result), self._instance_id, request)
        elif t == 'success':
            response = jcoms.StoreResponse()
            for module in result:
                module_pb = response.modules.add()
                self._module_to_pb(module, module_pb)
            self._coms.send(response, self._instance_id, request)
        else:
            log.error('_on_store_callback(): shouldnt get here')

    def _notify_modules_changed(self):
        for instanceId, instance in Instance.instances.items():
            if instance.is_active:
                instance._on_settings()

    def _on_dataset_set(self, request, response):
        if request.incData:
            self._apply_cells(request, response)
        if request.incSchema:
            self._apply_schema(request, response)

    def _on_dataset_get(self, request, response):
        if request.incSchema:
            self._populate_schema(request, response)
        if request.incData:
            self._populate_cells(request, response)

    def _apply_schema(self, request, response):
        for i in range(len(request.schema)):
            column_schema = request.schema[i]
            column = self._data.dataset.get_column_by_id(column_schema.id)

            levels = None
            if column_schema.hasLevels:
                levels = [ ]
                for level in column_schema.levels:
                    levels.append((level.value, level.label))

            column.change(column_schema.measureType, column_schema.name, levels, auto_measure=column_schema.autoMeasure)

            response.incSchema = True
            schema = response.schema.add()
            self._populate_column_schema(column, schema)

        self._data.dataset.is_edited = True

    def _apply_cells(self, request, response):
        row_start = request.rowStart
        col_start = request.columnStart
        row_end   = request.rowEnd
        col_end   = request.columnEnd
        row_count = row_end - row_start + 1
        col_count = col_end - col_start + 1

        for i in range(col_count):
            column = self._data.dataset[col_start + i]
            col_res = request.data[i]

            changes = column.changes

            if column.measure_type == MeasureType.CONTINUOUS:
                nan = float('nan')
                for j in range(row_count):
                    cell = col_res.values[j]
                    if cell.HasField('o'):
                        if cell.o == jcoms.SpecialValues.Value('MISSING'):
                            column[row_start + j] = nan
                    elif cell.HasField('d'):
                        column[row_start + j] = cell.d
                    elif cell.HasField('i'):
                        column[row_start + j] = cell.i
                    elif cell.HasField('s') and column.auto_measure:
                        column.change(MeasureType.NOMINAL_TEXT)
                        index = column.level_count
                        column.insert_level(index, cell.s)
                        column[row_start + j] = index

            elif column.measure_type == MeasureType.NOMINAL_TEXT:
                for j in range(row_count):
                    cell = col_res.values[j]
                    if cell.HasField('o'):
                        if cell.o == jcoms.SpecialValues.Value('MISSING'):
                            column[row_start + j] = -2147483648
                    else:
                        if cell.HasField('s'):
                            value = cell.s
                            if value == '':
                                value = -2147483648
                        elif cell.HasField('d'):
                            value = cell.d
                            if math.isnan(value):
                                value = -2147483648
                            else:
                                value = str(value)
                        else:
                            value = cell.i

                        column.clear_at(row_start + j)  # necessary to clear first with NOMINAL_TEXT

                        if value == -2147483648:
                            index = -2147483648
                        elif not column.has_level(value):
                            index = column.level_count
                            column.insert_level(index, value)
                        else:
                            index = column.get_value_for_label(value)
                        column[row_start + j] = index
            else:
                for j in range(row_count):
                    cell = col_res.values[j]
                    if cell.HasField('o'):
                        if cell.o == jcoms.SpecialValues.Value('MISSING'):
                            column[row_start + j] = -2147483648
                    elif cell.HasField('i'):
                        value = cell.i
                        if not column.has_level(value) and value != -2147483648:
                            column.insert_level(value, str(value))
                        column[row_start + j] = value
                    elif cell.HasField('d') and column.auto_measure:
                        column.change(MeasureType.CONTINUOUS)
                        column[row_start + j] = cell.d
                    elif cell.HasField('s') and column.auto_measure:
                        column.change(MeasureType.NOMINAL_TEXT)
                        column.clear_at(row_start + j)  # necessary to clear first with NOMINAL_TEXT
                        value = cell.s
                        index = column.level_count
                        column.insert_level(index, value)
                        column[row_start + j] = index

            if column.auto_measure:
                self._auto_adjust(column)
            elif column.measure_type == MeasureType.CONTINUOUS:
                column.determine_dps()

            if changes != column.changes:
                response.incSchema = True
                schema = response.schema.add()
                self._populate_column_schema(column, schema)

            self._data.dataset.is_edited = True

    def _auto_adjust(self, column):
        if column.measure_type == MeasureType.NOMINAL_TEXT:
            for level in column.levels:
                try:
                    int(level[1])
                except ValueError:
                    break
            else:
                column.change(MeasureType.NOMINAL)
                return

            for level in column.levels:
                try:
                    float(level[1])
                except ValueError:
                    break
            else:
                column.change(MeasureType.CONTINUOUS)
                return

        elif column.measure_type == MeasureType.CONTINUOUS:
            for value in column:
                if math.isnan(value):
                    continue
                if round(value) != round(value, 6):
                    break
            else:
                column.change(MeasureType.NOMINAL)
                return

            column.determine_dps()

    def _populate_cells(self, request, response):

        row_start = request.rowStart
        col_start = request.columnStart
        row_end   = request.rowEnd
        col_end   = request.columnEnd
        row_count = row_end - row_start + 1
        col_count = col_end - col_start + 1

        for c in range(col_start, col_start + col_count):
            column = self._data.dataset[c]

            col_res = response.data.add()

            if column.measure_type == MeasureType.CONTINUOUS:
                for r in range(row_start, row_start + row_count):
                    cell = col_res.values.add()
                    value = column[r]
                    if math.isnan(value):
                        cell.o = jcoms.SpecialValues.Value('MISSING')
                    else:
                        cell.d = value
            elif column.measure_type == MeasureType.NOMINAL_TEXT:
                for r in range(row_start, row_start + row_count):
                    cell = col_res.values.add()
                    value = column[r]
                    if value == '':
                        cell.o = jcoms.SpecialValues.Value('MISSING')
                    else:
                        cell.s = value
            else:
                for r in range(row_start, row_start + row_count):
                    cell = col_res.values.add()
                    value = column[r]
                    if value == -2147483648:
                        cell.o = jcoms.SpecialValues.Value('MISSING')
                    else:
                        cell.i = value

    def _populate_schema(self, request, response):
        response.incSchema = True
        for column in self._data.dataset:
            column_schema = response.schema.add()
            self._populate_column_schema(column, column_schema)

    def _populate_column_schema(self, column, column_schema):
        column_schema.name = column.name
        column_schema.importName = column.import_name
        column_schema.id = column.id

        column_schema.measureType = column.measure_type.value
        column_schema.autoMeasure = column.auto_measure
        column_schema.width = 100
        column_schema.dps = column.dps

        column_schema.hasLevels = True

        if column.measure_type is MeasureType.NOMINAL_TEXT:
            for level in column.levels:
                level_pb = column_schema.levels.add()
                level_pb.label = level[1]
        elif column.measure_type is MeasureType.NOMINAL or column.measure_type is MeasureType.ORDINAL:
            for level in column.levels:
                level_pb = column_schema.levels.add()
                level_pb.value = level[0]
                level_pb.label = level[1]

    def _add_to_recents(self, path):

        settings = Settings.retrieve('backstage')
        recents  = settings.get('recents', [ ])

        for recent in recents:
            if path == recent['path']:
                recents.remove(recent)
                break

        name = os.path.basename(path)
        location = os.path.dirname(path)

        location = Instance._virtualise_path(location)

        recents.insert(0, { 'name': name, 'path': path, 'location': location })
        recents = recents[0:5]

        settings.set('recents', recents)
        settings.sync()

        for instanceId, instance in Instance.instances.items():
            if instance.is_active:
                instance._on_settings()

    def _on_settings(self, request=None):

        settings = Settings.retrieve('backstage')

        recents = settings.get('recents', [ ])

        response = jcoms.SettingsResponse()

        for recent in recents:
            recent_pb = response.recents.add()
            recent_pb.name = recent['name']
            recent_pb.path = recent['path']
            recent_pb.location = recent['location']

        try:
            path = os.path.join(conf.get('examples_path'), 'index.yaml')
            with open(path, encoding='utf-8') as index:
                for example in yaml.safe_load(index):
                    example_pb = response.examples.add()
                    example_pb.name = example['name']
                    example_pb.path = '{{Examples}}/' + example['path']
                    example_pb.description = example['description']
        except Exception as e:
            log.exception(e)

        for module in Modules.instance():
            module_pb = response.modules.add()
            self._module_to_pb(module, module_pb)

        self._coms.send(response, self._instance_id, request)

    def _module_to_pb(self, module, module_pb):
        module_pb.name = module.name
        module_pb.title = module.title
        module_pb.version.major = module.version[0]
        module_pb.version.minor = module.version[1]
        module_pb.version.revision = module.version[2]
        module_pb.description = module.description
        module_pb.authors.extend(module.authors)
        module_pb.path = module.path
        module_pb.isSystem = module.is_sys

        for analysis in module.analyses:
            analysis_pb = module_pb.analyses.add()
            analysis_pb.name = analysis.name
            analysis_pb.ns = analysis.ns
            analysis_pb.title = analysis.title
            analysis_pb.menuGroup = analysis.menuGroup
            analysis_pb.menuSubgroup = analysis.menuSubgroup
            analysis_pb.menuTitle = analysis.menuTitle
            analysis_pb.menuSubtitle = analysis.menuSubtitle

    def _on_engine_event(self, event):
        if event['type'] == 'terminated' and self._coms is not None:
            self._coms.close()
