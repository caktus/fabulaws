from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import *
from fabulaws.api import *


class RedisMixin(object):
    """
    FabulAWS Ubuntu mixin that installs and configures Redis.
    """
    redis_ppa = None
    redis_packages = ['redis-server']
    redis_bind = '127.0.0.1' # set to '' to bind to all interfaces
    redis_loglevel = 'notice'
    redis_conf = '/etc/redis/redis.conf'
    redis_bind_pattern = '#?\s*bind 127\.0\.0\.1'
    redis_loglevel_pattern = '#?\s*loglevel \w+'

    @uses_fabric
    def _redis_configure(self, bind=None, loglevel=None):
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
        sudo('service redis-server restart', pty=False) # must pass pty=False

    def setup(self):
        """Redis mixin"""

        super(RedisMixin, self).setup()
        if self.redis_ppa:
            self.add_ppa(self.redis_ppa)
        self.install_packages(self.redis_packages)
        self._redis_configure()
