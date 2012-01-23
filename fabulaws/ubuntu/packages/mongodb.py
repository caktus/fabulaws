from fabulaws.ubuntu.packages.base import AptMixin


class MongoDbMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures MongoDB from the
    distro-supplied apt package ``mongodb-server``.
    """
    package_name = 'mongodb'
    mongodb_packages = ['mongodb-server']


class MongoDb10genMixin(MongoDbMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures MongoDB from the 10gen
    apt repository, which tends to be more up to date.
    """
    mongodb_aptrepo = ('http://downloads-distro.mongodb.org/repo/ubuntu-upstart', 'dist', '10gen', '7F0CEB10')
    mongodb_packages = ['mongodb-10gen']
