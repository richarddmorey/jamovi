
'use strict';

const $ = require('jquery');
const ProtoBuf = require('protobufjs');
const Q = require('q');
const PB = require('./jamovi_pb');

const Coms = function() {

    this._baseUrl = null;
    this._transId = 0;
    this._transactions = [ ];
    this._listeners = [ ];

    this.connected = null;
    this.Messages = PB.jamovi.coms;

    this.ready = new Promise((resolve, reject) => {
        this._notifyReady = resolve;
    });
};

Coms.prototype.setBaseUrl = function(url) {
    this._baseUrl = url;
    this._notifyReady();
};

Coms.prototype.connect = function(sessionId) {

    if ( ! this.connected) {

        this.connected = new Promise((resolve, reject) => {

            let url = this._baseUrl + 'coms';
            url = url.replace('http', 'ws'); // http -> ws, https -> wss

            if (sessionId)
                url += '/' + sessionId;

            this._ws = new WebSocket(url);
            this._ws.binaryType = 'arraybuffer';

            this._ws.onopen = () => {
                console.log('opened!');
                resolve();
            };

            this._ws.onmessage = (event) => {
                this.receive(event);
            };

            this._ws.onerror = reject;
            this._ws.onclose = (msg) => {
                console.log('websocket closed!');
                console.log(msg);
                this._notifyEvent('close');
            };
        });
    }

    return this.connected;
};

Coms.prototype.sendP = function(request) {
    this._transId++;
    request.id = this._transId;
    let encoded = this.Messages.ComsMessage.encode(request).finish();
    this._ws.send(encoded);
};

Coms.prototype.send = function(request) {

    return new Q.promise((resolve, reject, onprogress) => {

        this._transId++;

        request.id = this._transId;
        let encoded = this.Messages.ComsMessage.encode(request).finish();
        this._ws.send(encoded);

        this._transactions.push({
            id : this._transId,
            resolve : resolve,
            reject  : reject,
            onprogress : onprogress,
            requestTime : new Date()
        });
    });
};

Coms.prototype.receive = function(event) {

    let uint8 = new Uint8Array(event.data);
    let response = this.Messages.ComsMessage.decode(uint8);

    if (response.id === 0) {
        this._notifyEvent('broadcast', response);
        return;
    }

    var found = false;

    for (var i = 0; i < this._transactions.length; i++) {

        var trans = this._transactions[i];
        if (trans.id === response.id) {
            found = true;
            if (response.status === this.Messages.Status.COMPLETE)
                trans.resolve(response);
            else if (response.status === this.Messages.Status.ERROR)
                trans.reject(response.error);
            else
                trans.onprogress(response);
            break;
        }
    }

    if ( ! found)
        this._notifyEvent('broadcast', response);

};

Coms.prototype.on = function(eventName, callback) {
    this._listeners.push({ eventName, callback });
};

Coms.prototype.off = function(eventName, callback) {
    this._listeners = this._listeners.filter(v => v.eventName !== eventName || v.callback !== callback);
};

Coms.prototype._notifyEvent = function(eventName, event) {
    for (let listener of this._listeners) {
        if (listener.eventName === eventName)
            listener.callback(event);
    }
};

module.exports = Coms;
