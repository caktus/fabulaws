import datetime

from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import *
from fabulaws.api import *
from fabulaws.ubuntu.packages.base import AptMixin

class MemcachedMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures memcached.
    """
    package_name = 'memcached'
    memcached_packages = ['memcached']
    memcached_ulimit = 10000
    memcached_bind = '127.0.0.1' # set to '' to bind to all interfaces
    memcached_memory = '64'
    memcached_connections = '1024'
    memcached_conf = '/etc/memcached.conf'
    memcached_init_default = '/etc/default/memcached'
    memcached_conf_patterns = {
        'bind': ('-l', r'\S+'),
        'connections': ('-c', r'\w+'),
        'memory': ('-m', r'\w+'),
        'threads': ('-t', r'\w+')
    }

    @uses_fabric
    def memcached_service(self, cmd):
        sudo('/etc/init.d/memcached {0}'.format(cmd), pty=False)

    @uses_fabric
    def memcached_configure(self, **kwargs):
        for key, (opt, pat) in self.memcached_conf_patterns.iteritems():
            if key in kwargs:
                val = kwargs[key]
            else:
                val = getattr(self, 'memcached_{0}'.format(key), None)
            if val is None:
                continue
            full_pat = '^#?\s*{0}\s+{1}'.format(opt, pat)
            full_val = '{0} {1}'.format(opt, val)
            # we don't know if the config file contains the line or not, so
            # comment it out if it does and then add a new line with the date
            files.comment(self.memcached_conf, full_pat, use_sudo=True)
            if val != '':
                date = datetime.datetime.now().strftime('%Y-%m-%d')
                message = '\n# {0}; added by fabulaws {1}\n{2}'\
                          ''.format(key, date, full_val)
                files.append(self.memcached_conf, message, use_sudo=True)
        if self.memcached_ulimit is not None:
            ulimit = 'ulimit -n {0}'.format(self.memcached_ulimit)
            files.append(self.memcached_init_default, ulimit, use_sudo=True)
        self.memcached_service('restart')

    def setup(self):
        """memcached mixin"""

        super(MemcachedMixin, self).setup()
        self.memcached_configure()
