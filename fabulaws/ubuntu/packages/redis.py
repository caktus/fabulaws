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
    redis_conf = '/etc/redis/redis.conf'
    redis_bind_pattern = '#?\s*bind 127\.0\.0\.1'
    redis_loglevel_pattern = '#?\s*loglevel \w+'

    @uses_fabric
    def redis_service(self, cmd):
        sudo('service redis-server {0}'.format(cmd), pty=False) # must pass pty=False

    @uses_fabric
    def redis_configure(self, bind=None, loglevel=None):
        if bind is None:
            bind = self.redis_bind
        if loglevel is None:
            loglevel = self.redis_loglevel
        if bind == '': # all interfaces
            files.comment(self.redis_conf, self.redis_bind_pattern,
                          use_sudo=True)
        else:
            files.sed(self.redis_conf, self.redis_bind_pattern, bind,
                      use_sudo=True)
        loglevel = 'loglevel {0}'.format(loglevel)
        files.sed(self.redis_conf, self.redis_loglevel_pattern, loglevel,
                  use_sudo=True)
        self.redis_service('restart')

    def secure_directories(self, *args, **kwargs):
        # make sure we stop first in case we're being moved to a secure directory
        self.redis_service('stop')
        super(RedisMixin, self).secure_directories(*args, **kwargs)
        self.redis_service('start')

    def setup(self):
        """Redis mixin"""

        super(RedisMixin, self).setup()
        self.redis_configure()


class RedisPpaMixin(RedisMixin):
    """
    Redis mixin using the Rowan PPA from:
    https://launchpad.net/~rwky/+archive/redis
    """

    redis_ppa = 'ppa:rwky/redis'
    redis_packages = ['redis-server']
