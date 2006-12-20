"""Provides convenient access to SQLObject-managed and/or SQLAlchemy-managed
databases.

This module enables easy use of an SQLObject database by providing an 
auto-connect hub that will utilize the db uri string given in the Paste conf
file called ``sqlobject.dburi``.

It provides the SQLAlchemy db_session variable. This database session is bound
to an automatically configured database engine, its source specified by the
``sqlalchemy.dburi`` uri in the Paste conf file.
"""
import thread
from paste.deploy.config import CONFIG
from paste.deploy.converters import asbool

import pylons

__all__ = ["PackageHub", "AutoConnectHub"]

# Provide support for sqlalchemy
try:
    import sqlalchemy
    from sqlalchemy.ext import sessioncontext

    def create_engine(uri=None):
        """Create a SQLAlchemy db engine"""
        config = CONFIG['app_conf']
        uri = config.get("sqlalchemy.dburi")
        if not uri:
            raise KeyError("No sqlalchemy database config found!")
        echo = asbool(config.get("sqlalchemy.echo", False))
        engine = sqlalchemy.create_engine(uri, echo=echo)
        return engine

    def make_session():
        """Creates a session using using the ``g._db_engine`` value
        
        If the ``g._db_engine`` variable does not exist, a new engine will be
        created and attached there.
        """
        if not hasattr(pylons.g, '_db_engine'):
            pylons.g._db_engine = create_engine()
        return sqlalchemy.create_session(bind_to=pylons.g._db_engine)

    def app_scope():
        """Return the id keying the current database session's scope.

        The session is particular to the current Pylons application -- this
        returns an id generated from the current thread and the current Pylons
        application's Globals object.
        """
        return '%i|%i' % (thread.get_ident(), id(pylons.g._current_obj()))

    session_context = sessioncontext.SessionContext(make_session,
                                                    scopefunc=app_scope)
    try:
        db_session = session_context.current
    except:
        db_session = None

    __all__.extend(['create_engine', 'make_session', 'app_scope',
                    'session_context', 'db_session'])

except ImportError:
    pass

# Provide support for sqlobject
try:
    import sqlobject
    from sqlobject.dbconnection import ConnectionHub, Transaction, TheURIOpener
except:
    ConnectionHub = object

class AutoConnectHub(ConnectionHub):
    """Connects to the database once per thread.
    
    The AutoConnectHub also provides convenient methods for managing transactions.
    """
    uri = None
    params = {}
    
    def __init__(self, uri=None, pool_connections=True):
        if not uri:
            uri = CONFIG['app_conf'].get('sqlobject.dburi')
        self.uri = uri
        self.pool_connections = pool_connections
        ConnectionHub.__init__(self)
    
    def getConnection(self):
        try:
            conn = self.threadingLocal.connection
            return conn
        except AttributeError:
            if self.uri:
                conn = sqlobject.connectionForURI(self.uri)
                # the following line effectively turns off the DBAPI connection
                # cache. We're already holding on to a connection per thread,
                # and the cache causes problems with sqlite.
                if self.uri.startswith("sqlite"):
                    TheURIOpener.cachedURIs = {}
                self.threadingLocal.connection = conn
                if not self.pool_connections:
                    # This disables pooling
                    conn._pool = None
                return conn
            try:
                return self.processConnection
            except AttributeError:
                raise AttributeError(
                    "No connection has been defined for this thread "
                    "or process")
    
    def begin(self):
        """Starts a transaction."""
        conn = self.getConnection()
        if isinstance(conn, Transaction):
            if conn._obsolete:
                conn.begin()
            return
        self.threadingLocal.old_conn = conn
        self.threadingLocal.connection = conn.transaction()
        
    def commit(self):
        """Commits the current transaction."""
        conn = self.threadingLocal.connection
        if isinstance(conn, Transaction):
            self.threadingLocal.connection.commit()
    
    def rollback(self):
        """Rolls back the current transaction."""
        conn = self.threadingLocal.connection
        if isinstance(conn, Transaction) and not conn._obsolete:
            self.threadingLocal.connection.rollback()
            
    def end(self):
        """Ends the transaction, returning to a standard connection."""
        conn = self.threadingLocal.connection
        if not isinstance(conn, Transaction):
            return
        if not conn._obsolete:
            conn.rollback()
        self.threadingLocal.connection = self.threadingLocal.old_conn
        del self.threadingLocal.old_conn
        self.threadingLocal.connection.cache.clear()

# This dictionary stores the AutoConnectHubs used for each
# connection URI
_hubs = dict()

class UnconfiguredConnectionError(KeyError):
    """
    Raised when no configuration is available to set up a connection.
    """

class PackageHub(object):
    """Transparently proxies to an AutoConnectHub for the URI
    that is appropriate for this package. A package URI is
    configured via "packagename.dburi" in the Paste ini file
    settings. If there is no package DB URI configured, the
    default (provided by "sqlobject.dburi") is used.
    
    The hub is not instantiated until an attempt is made to
    use the database.

    If pool_connections=False, then a new database connection
    will be opened for every request.  This will avoid
    problems with database connections that periodically die.
    """
    def __init__(self, packagename, dburi=None, pool_connections=True):
        self.packagename = packagename
        self.hub = None
        self.dburi = dburi
        self.pool_connections = pool_connections
    
    def __get__(self, obj, type):
        if not self.hub:
            try:
                self.set_hub()
            except UnconfiguredConnectionError, e:
                raise AttributeError(str(e))
        return self.hub.__get__(obj, type)
    
    def __set__(self, obj, type):
        if not self.hub:
            self.set_hub()
        return self.hub.__set__(obj, type)
    
    def __getattr__(self, name):
        if not self.hub:
            self.set_hub()
        return getattr(self.hub, name)
    
    def set_hub(self):
        dburi = self.dburi
        if not dburi:
            try:
                appconf = CONFIG['app_conf']
            except TypeError, e:
                # No configuration is registered
                raise UnconfiguredConnectionError(str(e))
            dburi = appconf.get("%s.dburi" % self.packagename)
            if not dburi:
                dburi = appconf.get("sqlobject.dburi")
        if not dburi:
            raise UnconfiguredConnectionError(
                "No database configuration found!")
        hub = _hubs.get(dburi)
        if not hub:
            hub = AutoConnectHub(
                dburi, pool_connections=self.pool_connections)
            _hubs[dburi] = hub
        self.hub = hub
