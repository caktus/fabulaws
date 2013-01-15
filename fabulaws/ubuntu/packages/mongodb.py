from fabric.api import *

from fabulaws.decorators import *
from fabulaws.ubuntu.packages.base import AptMixin


class MongoDbMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures MongoDB from the
    distro-supplied apt package ``mongodb-server``.
    """
    package_name = 'mongodb'
    mongodb_packages = ['mongodb-server']

    @uses_fabric
    def mongodb_service(self, cmd):
        sudo('service mongodb {0}'.format(cmd))

    def secure_directories(self, *args, **kwargs):
        # make sure we stop first in case we're being moved to a secure directory
        self.mongodb_service('stop')
        super(MongoDbMixin, self).secure_directories(*args, **kwargs)
        self.mongodb_service('start')


class MongoDb10genMixin(MongoDbMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures MongoDB from the 10gen
    apt repository, which tends to be more up to date.
    """
    mongodb_aptrepo = ('http://downloads-distro.mongodb.org/repo/ubuntu-upstart', 'dist', '10gen', '7F0CEB10')
    mongodb_packages = ['mongodb-10gen']
