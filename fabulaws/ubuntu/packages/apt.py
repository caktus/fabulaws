from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric

class AptMixin(object):
    """
    FabulAWS mixin for manipulating Debian-based packages and their
    repositories
    """

    def _read_lines_from_file(self, file_name):
        with open(file_name) as f:
            packages = f.readlines()
        return map(lambda x: x.strip('\n\r'), packages)

    @uses_fabric
    def install_packages(self, *packages):
        """Install apt packages from a list."""

        sudo(u"apt-get install -y %s" % u" ".join(packages))

    @uses_fabric
    def install_packages_from_file(self, file_name):
        """Install apt packages from a file list."""

        self.install_packages(*self._read_lines_from_file(file_name))

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

        sudo(u"add-apt-repository %s" % name)
        self.update_apt_sources()

    @uses_fabric
    def add_ppas_from_file(self, file_name):
        """Add personal package archive from a file list."""

        for ppa in self._read_lines_from_file(file_name):
            self.add_ppa(ppa)
