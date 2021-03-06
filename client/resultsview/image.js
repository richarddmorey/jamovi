'use strict';

const _ = require('underscore');
const $ = require('jquery');
const Backbone = require('backbone');
Backbone.$ = $;

const ResultsElement = require('./element');

const ImageModel = Backbone.Model.extend({
    defaults : {
        name: "name",
        title: "(no title)",
        element: {
            path: "",
            width: 400,
            height: 300
        },
        error: null,
        status: 'complete'
    },
    initialize: function() {
    }
});

const ImageView = ResultsElement.View.extend({
    initialize: function(data) {

        ResultsElement.View.prototype.initialize.call(this, data);

        this.$el.addClass('silky-results-image');

        this.$title = $('<h' + (this.level+1) + ' class="silky-results-image-title"></h' + (this.level+1) + '>');
        this.$title.appendTo(this.$el);

        if (this.model === null)
            this.model = new ImageModel();

        this.render();
    },
    type: function() {
        return "Image";
    },
    render: function() {

        this.$title.text(this.model.attributes.title);

        let element = this.model.attributes.element;

        let backgroundImage = 'none';
        if (element.path !== null) {
            let url = 'res/' + element.path;
            url = url.replace(/\"/g, '&quot;');
            backgroundImage = "url('" + url + "')";
        }

        $('<div style=" \
            background-image: ' + backgroundImage + '; \
            width: ' + element.width + 'px ; \
            height: ' + element.height + 'px ; \
            background-size: ' + element.width + 'px ; \
            ">').appendTo(this.$el);

    }
});

module.exports = { Model: ImageModel, View: ImageView };
