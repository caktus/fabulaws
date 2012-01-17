import re
import datetime

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
    redis_bind = '127.0.0.1'
    redis_conf = '/etc/redis/redis.conf'
    redis_bind_pattern = '#?\w*bind 127\.0\.0\.1'

    @uses_fabric
    def redis_set_bind_addr(self, bind):
        if bind is None:
            files.comment(self.redis_conf, self.redis_bind_pattern,
                          use_sudo=True)
        else:
            files.sed(self.redis_conf, self.redis_bind_pattern, self.redis_bind,
                      use_sudo=True)
        sudo('service redis-server restart')

    def setup(self):
        """Redis mixin"""

        super(RedisMixin, self).setup()
        if self.redis_ppa:
            self.add_ppa(self.redis_ppa)
        self.install_packages(self.redis_packages)
        self.redis_set_bind_addr(self.redis_bind)
