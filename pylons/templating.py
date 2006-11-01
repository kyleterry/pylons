"""Buffet templating plugin and render functions

The Buffet object is styled after the original Buffet module that implements
template language neutral rendering for CherryPy. This version of Buffet also
contains caching functionality that utilizes 
`Beaker middleware <http://beaker.groovie.org/>`_ to provide template language
neutral caching functionality.

A customized version of 
`BuffetMyghty <http://projects.dowski.com/projects/buffetmyghty>`_ is included
that provides a template API hook as the ``pylonsmyghty`` engine. This version
of BuffetMyghty disregards some of the TurboGears API spec so that traditional
Myghty template names can be used with ``/`` and file extensions.

The render functions are intended as the primary user-visible rendering 
commands and hook into Buffet to make rendering content easy.
"""
import pkg_resources
import os
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO
import paste.wsgiwrappers
import pylons

PYLONS_VARS = ['c', 'h', 'g', '_', 'request', 'session', 'params']

class BuffetError(Exception):
    """Buffet Exception"""
    pass

class Buffet(object):
    """Buffet style plug-in template rendering
    
    Buffet implements template language plug-in support modeled highly on the
    `Buffet Project <http://projects.dowski.com/projects/buffet>`_ from which
    this class inherits its name.
    """
    def __init__(self, default_engine=None, template_root=None, 
        default_options=None, **config):
        """Initialize the Buffet renderer, and optionally set a default
        engine/options"""
        if default_options is None:
            default_options = {}
        self.default_engine = default_engine
        self.template_root = template_root
        self.default_options = default_options
        self.engines = {}
        if self.default_engine:
            self.prepare(default_engine, template_root, **config)
        
    def prepare(self, engine_name, template_root=None, alias=None, **config):
        """Prepare a template engine for use
        
        This method must be run before the `render <#render>`_ method is called
        so that the ``template_root`` and options can be set. Template engines
        can also be aliased if you wish to use multiplate configurations of the
        same template engines, or prefer a shorter name when rendering a template
        with the engine of your choice.
        """
        Engine = available_engines.get(engine_name, None)
        if not Engine:
            raise TemplateEngineMissing('Please install a plugin for '
                '"%s" to use its functionality' % engine_name)
        engine_name = alias or engine_name
        defaults = config.pop('default_options', None)
        self.engines[engine_name] = \
            dict(engine=Engine(options=config), root=template_root)
    
    def _update_names(self, ns):
        """Given a dict, update the dict with the Pylons vars and their 
        respective objects"""
        d = ns
        d.update(dict(
            c=pylons.c._current_obj(),
            h=pylons.h._current_obj(),
            request=pylons.request._current_obj(),
            g=pylons.g._current_obj(),
            session=pylons.session._current_obj(),
            s=pylons.session._current_obj(),
            _=pylons.util._,
            render=render,
        ))
        return d
    
    def render(self, engine_name=None, template_name=None,
        include_pylons_variables=True, namespace=None, 
        cache_key=None, cache_expire=None, cache_type=None, **options):
        """Render a template using a template engine plug-in
        
        To use templates it is expected that you will attach data to be used in
        the template to the ``c`` variable which is available in the controller
        and the template. 
        
        When porting code from other projects it is sometimes easier to use an
        exisitng dictionary which can be specified with ``namespace``.
        
        ``engine_name``
            The name of the template engine to use, which must be
            'prepared' first.
        ``template_name``
            Name of the template to render
        ``include_pylons_variables``
            If a custom namespace is specified this determines whether Pylons 
            variables are included in the namespace or not. Defaults to 
            ``True``.
        ``namespace``
            A custom dictionary of names and values to be substituted in the
            template. If ``include_pylons_variables`` is ``True`` and any
            keys in ``namespace`` conflict with names of Pylons variables, 
            an error is raised.
        
        Caching options (uses Beaker caching middleware)
        
        ``cache_key``
            Key to cache this copy of the template under.
        ``cache_type``
            Valid options are ``dbm``, ``file``, ``memory``, or 
            ``ext:memcached``.
        ``cache_expire``
            Time in seconds to cache this template with this ``cache_key`` for.
            Or use 'never' to designate that the cache should never expire.
        
        The minimum key required to trigger caching is ``cache_expire='never'``
        which will cache the template forever seconds with no key.
        
        All other keyword options are passed directly to the template engine
        used.
        """
        if not engine_name and self.default_engine:
            engine_name = self.default_engine
        engine_config = self.engines.get(engine_name)
        
        if not engine_config:
            raise Exception, \
                "No engine with that name configured: %s" % engine_name
        
        full_path = template_name
                
        if engine_name == 'pylonsmyghty':
            if namespace is None:
                namespace = {}
            namespace['_global_args'] = self._update_names({})

            # Reserved myghty keywords
            for key in ('output_encoding', 'encoding_errors', 
                        'disable_unicode'):
                if key in namespace:
                    options[key] = namespace.pop(key)
            
            # If they passed in a variable thats listed in the global_args,
            # update the global args one instead of duplicating it
            interp = engine_config['engine'].interpreter
            for key in interp.global_args.keys() + \
                interp.init_params.get('allow_globals', []):
                if key in namespace:
                    namespace['_global_args'][key] = namespace.pop(key)
        else:
            if namespace is None:
                if not include_pylons_variables:
                    raise BuffetError('You must specify ``namespace`` if \
                        ``include_pylons_variables`` is False')
                else:
                    namespace = self._update_names({})
            elif isinstance(namespace, dict):
                if include_pylons_variables:
                    var_conflicts = list(
                        [x for x in PYLONS_VARS if x in namespace]
                    )
                    if var_conflicts:
                        raise Exception(
                            'The variable(s) %s specified in the namespace '
                            'conflicts with Pylons variable(s) of the same '
                            'name. Set ``include_pylons_variables`` to '
                            '``False`` if you do not want to use Pylons '
                            'variables in your template' % var_conflicts)
                    namespace = self._update_names(namespace)
            else:
                namespace = self._update_names(namespace)
            
            if not engine_name.startswith('pylons'):
                full_path = os.path.join(engine_config['root'], template_name)
                full_path = full_path.replace(os.path.sep, '.').lstrip('.')
        
        # If one of them is not None then the user did set something
        if cache_key is not None or cache_expire is not None or cache_type \
            is not None:
            if not cache_type:
                cache_type = 'dbm'
            if not cache_key:
                cache_key = 'default'     
            if cache_expire == 'never':
                cache_expire = None
            def content():
                return engine_config['engine'].render(namespace, 
                    template=full_path, **options)
            tfile = full_path
            if options.get('fragment', False):
                tfile += '_frag'
            mycache = pylons.cache.get_cache(tfile)
            content = mycache.get_value(cache_key, createfunc=content, 
                type=cache_type, expiretime=cache_expire)
            return content
        
        return engine_config['engine'].render(namespace, template=full_path, 
            **options)
        
class TemplateEngineMissing(Exception):
    """Exception to toss when an engine is missing"""
    pass

class MyghtyTemplatePlugin(object):
    """Myghty Template Plugin
    
    This Myghty Template Plugin varies from the official BuffetMyghty in that 
    it will properly populate all the default Myghty variables needed and 
    render fragments.
    """
    extension = "myt"

    def __init__(self, extra_vars_func=None, options=None):
        """Initialize Myghty template engine"""
        if options is None:
            options = {}
        myt_opts = {}
        for k, v in options.iteritems():
            if k.startswith('myghty.'):
                myt_opts[k[7:]] = v
        import myghty.interp
        self.interpreter = myghty.interp.Interpreter(**myt_opts)
    
    def load_template(self, template_path):
        """Unused method for TG plug-in API compatibility"""
        pass

    def render(self, info, format="html", fragment=False, template=None,
               output_encoding=None, encoding_errors=None,
               disable_unicode=None):
        """Render the template indicated with info as the namespace and globals
        from the ``info['_global_args']`` key."""
        buf = StringIO()
        global_args = info.pop('_global_args')
        optional_args = {}
        if fragment:
            optional_args['disable_wrapping'] = True
        if output_encoding:
            optional_args['output_encoding'] = output_encoding
        if encoding_errors:
            optional_args['encoding_errors'] = encoding_errors
        if disable_unicode:
            optional_args['disable_unicode'] = disable_unicode
        self.interpreter.execute(template, request_args=info,
                                 global_args=global_args, out_buffer=buf,
                                 **optional_args)
        return buf.getvalue()

available_engines = {}

for entry_point in pkg_resources.iter_entry_points('python.templating.engines'):
    Engine = entry_point.load()
    available_engines[entry_point.name] = Engine

def render(*args, **kargs):
    """Render a template and return it as a string (possibly Unicode)
    
    Optionally takes 3 keyword arguments to use caching supplied by Buffet.
    
    Example::
        
        >>> content = render('/my/template.myt')
        >>> print content
        >>> content = render('/my/template.myt', fragment=True)
    
    .. admonition:: Note
        
        Not all template languages support the concept of a fragment. In those
        template languages that do support the fragment option, this usually 
        implies that the template will be rendered without extending or 
        inheriting any site skin.
    """
    fragment = kargs.pop('fragment', False)
    args = list(args)
    template = args.pop()
    cache_args = dict(cache_expire=kargs.pop('cache_expire', None), 
                       cache_type=kargs.pop('cache_type', None),
                       cache_key=kargs.pop('cache_key', None))
    if args: 
        engine = args.pop()
        return pylons.buffet.render(engine, template, fragment=fragment,
                                    namespace=kargs, **cache_args)
    return pylons.buffet.render(template_name=template, fragment=fragment,
                                namespace=kargs, **cache_args)

def render_response(*args, **kargs):
    """Returns the rendered response within a Response object
    
    See ``render`` for information on rendering.
    
    Example:
    
    .. code-block:: Python
        
        def view(self):
            return render_response('/my/template.myt')
    """
    response = pylons.Response(render(*args, **kargs))
    output_encoding = kargs.get('output_encoding')
    encoding_errors = kargs.get('encoding_errors')
    if output_encoding:
        response.headers['Content-Type'] = '%s; charset=%s' % \
            (paste.wsgiwrappers.settings['content_type'], output_encoding)
    if encoding_errors:
        response.encoding_errors = encoding_errors
    return response


__pudge_all__ = ['render', 'render_response', 'Buffet', 'MyghtyTemplatePlugin']
__all__ = ['render', 'render_response', 'Buffet', 'MyghtyTemplatePlugin']
