//
// Copyright (C) 2016 Jonathon Love
//

'use strict';

const _ = require('underscore');
const $ = require('jquery');
const Backbone = require('backbone');
Backbone.$ = $;
const util = require('util');

const PageModules = require('./store/pagemodules');
const PageSideload  = require('./store/pagesideload');
const tarp = require('./utils/tarp');

const Store = Backbone.View.extend({
    className: 'Store',
    initialize: function() {

        this.$el.addClass('jmv-store');

        this.$header = $('<div class="jmv-store-header"></div>').appendTo(this.$el);

        this.$close = $('<div class="jmv-store-button-close"><span class="mif-arrow-up"></span></div>').appendTo(this.$header);
        this.$close.on('click', event => this.hide());

        this.$tabContainer = $('<div class="jmv-store-tab-container"></div>').appendTo(this.$el);
        this.$tabContainer.on('click', event => this._tabClicked(event));

        for (let tab of [
            { name: 'installed', title: 'Installed' },
            { name: 'store', title: 'Available' },
            { name: 'sideload', title: 'Sideload'} ]) {

            let $tab = $(util.format('<div class="jmv-store-tab" data-tab="%s"><div class="jmv-store-tab-inner">%s</div></div>', tab.name, tab.title));
            $tab.appendTo(this.$tabContainer);
        }

        this.$tabs = this.$tabContainer.children();

        this.$highlight = $('<div class="jmv-store-tab-highlight"></div>').appendTo(this.$tabContainer);

        let $pageContainer = $('<div class="jmv-store-page-container"></div>').appendTo(this.$el);

        this.$pageInst  = $('<div class="jmv-store-page jmv-store-page-installed left"></div>').appendTo($pageContainer);
        this.$pageStore = $('<div class="jmv-store-page jmv-store-page-store"></div>').appendTo($pageContainer);
        this.$pageSideload = $('<div class="jmv-store-page jmv-store-page-sideload right"></div>').appendTo($pageContainer);

        this.pageInst  = new PageModules({ el: this.$pageInst, model: this.model });
        this.pageStore = new PageModules({ el: this.$pageStore, model: this.model.available() });
        this.pageSideload = new PageSideload({ el: this.$pageSideload, model: this.model });

        this.pageInst.on('notification', note => this.trigger('notification', note));
        this.pageStore.on('notification', note => this.trigger('notification', note));
        this.pageSideload.on('notification', note => this.trigger('notification', note));
        this.pageSideload.on('close', () => this.hide());

        this.$pages = $pageContainer.children();

        this._selectedIndex = null;
    },
    _setSelected: function(index) {

        this._selectedIndex = index;
        this.$tabs.removeClass('selected');
        let $selected = $(this.$tabs[index]);
        $selected.addClass('selected');

        let css = $selected.position();
        css.width = $selected.width();
        css.height = $selected.height();

        this.$highlight.css(css);

        let $selectedPage = $(this.$pages[index]);
        for (let i = 0; i < this.$pages.length; i++) {
            let $page = $(this.$pages[i]);
            if (i < index) {
                $page.removeClass('right');
                $page.addClass('left');
            }
            else if (i > index) {
                $page.removeClass('left');
                $page.addClass('right');
            }
            else {
                $page.removeClass('right');
                $page.removeClass('left');
            }
        }
    },
    _tabClicked: function(event) {

        let $target = $(event.target);
        let $tab = $target.closest(this.$tabs);
        if ($tab.length === 0)
            return;
        let index = this.$tabs.index($tab);
        this._setSelected(index);
    },
    visible: function() {
        return this.$el.hasClass('visible');
    },
    show: function() {
        this.$el.addClass('visible');
        if (this._selectedIndex === null)
            setTimeout(() => this._setSelected(1), 100);
        tarp.show(false, 0.3);
        this.model.available().retrieve();
    },
    hide: function() {
        this.$el.removeClass('visible');
        tarp.hide();
    }
});

module.exports = Store;
