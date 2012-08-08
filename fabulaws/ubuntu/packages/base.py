from decimal import Decimal

from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric

class BaseAptMixin(object):
    """
    FabulAWS mixin for manipulating Debian-based packages and their
    repositories
    """

    def _read_lines_from_file(self, file_name):
        with open(file_name) as f:
            packages = f.readlines()
        return map(lambda x: x.strip('\n\r'), packages)

    @uses_fabric
    def install_packages(self, packages):
        """Install apt packages from a list."""

        sudo(u"apt-get install -y %s" % u" ".join(packages))

    @uses_fabric
    def install_packages_from_file(self, file_name):
        """Install apt packages from a file list."""

        self.install_packages(self._read_lines_from_file(file_name))

    @uses_fabric
    def update_apt_sources(self):
        """Update apt source."""

        sudo(u"apt-get update")

    @uses_fabric
    def upgrade_packages(self):
        """Safe upgrade of all packages."""

        self.update_apt_sources()
        sudo(u"apt-get upgrade -y")

    @uses_fabric
    def add_ppa(self, name):
        """Add personal package archive."""

        release = Decimal(sudo(u"lsb_release -r").split(':')[1].strip())
        if release >= Decimal('12.04'):
            sudo(u"apt-add-repository -y %s" % name)
        else:
            sudo(u"apt-add-repository %s" % name)
        self.update_apt_sources()

    @uses_fabric
    def add_aptrepo(self, url, dist, repo_name, key_name=None, key_server=None):
        repo = ' '.join(['deb', url, dist, repo_name])
        files.append('/etc/apt/sources.list', repo, use_sudo=True)
        if key_server is None:
            key_server = 'keyserver.ubuntu.com'
        if key_name:
            sudo('apt-key adv --keyserver {0} --recv {1}'.format(key_server,
                                                                  key_name))
        self.update_apt_sources()

    @uses_fabric
    def add_ppas_from_file(self, file_name):
        """Add personal package archive from a file list."""

        for ppa in self._read_lines_from_file(file_name):
            self.add_ppa(ppa)


class AptMixinMetaclass(type):
    """
    Metaclass that grabs all ``attr_prefix`` attributes from base classes and
    merges them into the ``_package_names`` attribute.  Allows package mixins
    to be defined in a declarative syntax.
    """
    def __new__(cls, name, bases, attrs):
        new_class = super(AptMixinMetaclass,
                          cls).__new__(cls, name, bases, attrs)
        new_class._package_names = set([b.package_name for b in bases
                                        if hasattr(b, 'package_name')])
        if 'package_name' in attrs:
            new_class._package_names.add(attrs['package_name'])
        return new_class


class AptMixin(BaseAptMixin):

    __metaclass__ = AptMixinMetaclass

    def setup(self, propagate=True):
        super(AptMixin, self).setup()
        for attr_prefix in self._package_names:
            ppa = getattr(self, '%s_ppa' % attr_prefix, None)
            aptrepo = getattr(self, '%s_aptrepo' % attr_prefix, None)
            packages = getattr(self, '%s_packages' % attr_prefix, [])
            if ppa:
                self.add_ppa(ppa)
            if aptrepo:
                self.add_aptrepo(*aptrepo)
            self.install_packages(packages)
