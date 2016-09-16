from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import *
from fabulaws.api import *
from fabulaws.ubuntu.packages.base import AptMixin

class RedisMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures Redis.
    """
    package_name = 'redis'
    redis_packages = ['redis-server']
    redis_bind = '127.0.0.1' # set to '' to bind to all interfaces
    redis_loglevel = 'notice'
    redis_keepalive = 60
    redis_conf = '/etc/redis/redis.conf'
    redis_bind_pattern = '#?\s*bind 127\.0\.0\.1'
    redis_loglevel_pattern = '#?\s*loglevel \w+'
    redis_keepalive_pattern = '#?\s*tcp-keepalive \w+'

    @uses_fabric
    def redis_service(self, cmd):
        sudo('service redis-server {0}'.format(cmd), pty=False) # must pass pty=False

    @uses_fabric
    def redis_configure(self, bind=None, loglevel=None, keepalive=None):
        if bind is None:
            bind = self.redis_bind
        if loglevel is None:
            loglevel = self.redis_loglevel
        if keepalive is None:
            keepalive = self.redis_keepalive
        if bind == '': # all interfaces
            files.comment(self.redis_conf, self.redis_bind_pattern,
                          use_sudo=True)
        else:
            files.sed(self.redis_conf, self.redis_bind_pattern, bind,
                      use_sudo=True)
        loglevel = 'loglevel {0}'.format(loglevel)
        files.sed(self.redis_conf, self.redis_loglevel_pattern, loglevel,
                  use_sudo=True)
        keepalive = 'tcp-keepalive {}'.format(keepalive)
        files.sed(self.redis_conf, self.redis_keepalive_pattern, keepalive,
                  use_sudo=True)
        self.redis_service('restart')

    def bind_app_directories(self, *args, **kwargs):
        # make sure we stop first in case we're being moved to a secure directory
        self.redis_service('stop')
        super(RedisMixin, self).bind_app_directories(*args, **kwargs)
        self.redis_service('start')

    def setup(self):
        """Redis mixin"""

        super(RedisMixin, self).setup()
        self.redis_configure()
