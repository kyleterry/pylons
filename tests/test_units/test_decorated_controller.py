# -*- coding: utf-8 -*-
from paste.fixture import TestApp
from paste.registry import RegistryManager

import pylons
from pylons.controllers import DecoratedController
from pylons.decorators import expose
from turbojson.jsonify import jsonify

from __init__ import TestWSGIController, SetupCacheGlobal, ControllerWrap

pylons.buffet = pylons.templating.Buffet(default_engine='genshi')
class MyClass(object): 
    pass

@jsonify.when('isinstance(obj, MyClass)')
def jsonify_myclass(obj):
    return {'result':'wo-hoo!'}



class BasicDecoratedController(DecoratedController):
    
    @expose('json')
    def json(self):
        return dict(a='hello world', b=True)

    @expose('json', exclude_names=["b"])
    def excluded_b(self):
        return dict(a="visible", b="invisible")
    
    @expose('json')
    def custom(self): 
        return dict(custom=MyClass())
    
    @expose('json')
    @expose('xml', content_type='application/xml')
    def xml_or_json(self):
        return dict(name="John Carter", title='officer', status='missing')

class TestDecoratedController(TestWSGIController):
    def __init__(self, *args, **kargs):
        TestWSGIController.__init__(self, *args, **kargs)
        self.baseenviron = {}
        app = ControllerWrap(BasicDecoratedController)
        app = self.sap = SetupCacheGlobal(app, self.baseenviron)
        app = RegistryManager(app)
        self.app = TestApp(app)


    def setUp(self):
        TestWSGIController.setUp(self)
        self.baseenviron.update(self.environ)
        
    def test_simple_jsonification(self):
        self.baseenviron['pylons.routes_dict']['action']= 'json'
        resp = self.app.get('/json')
        print resp.body
        assert '{"a": "hello world", "b": true}' in resp.body
                
    def test_custom_jsonification(self):
        self.baseenviron['pylons.routes_dict']['action']= 'custom'
        resp = self.app.get('/custom')
        print resp.body
        assert "wo-hoo!" in resp.body