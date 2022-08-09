import logging
from decimal import Decimal

from fabric.api import settings, sudo
from fabric.contrib import files

from fabulaws.decorators import uses_fabric

logger = logging.getLogger(__name__)


class BaseAptMixin(object):
    """
    FabulAWS mixin for manipulating Debian-based packages and their
    repositories
    """

    def _read_lines_from_file(self, file_name):
        with open(file_name) as f:
            packages = f.readlines()
        return [x.strip("\n\r") for x in packages]

    @uses_fabric
    def install_packages(self, packages):
        """Install apt packages from a list."""

        sudo(
            "export DEBIAN_FRONTEND=noninteractive ; apt-get -qq -y install %s"
            % " ".join(packages)
        )

    @uses_fabric
    def install_packages_from_file(self, file_name):
        """Install apt packages from a file list."""
        self.install_packages(self._read_lines_from_file(file_name))

    @uses_fabric
    def update_apt_sources(self):
        """Update apt source."""
        logger.info("Update apt source.")
        with settings(warn_only=True):
            sudo(
                "export DEBIAN_FRONTEND=noninteractive ; apt-get -qq update || apt-get -qq update"
            )

    @uses_fabric
    def upgrade_packages(self):
        """Safe upgrade of all packages."""

        self.update_apt_sources()
        # make sure apt/dpkg keep our installed config files, if any, and don't
        # prompt for user input:
        logger.info("Upgrading Packages")
        sudo(
            "export DEBIAN_FRONTEND=noninteractive ; apt-get dist-upgrade -y "
            '-o Dpkg::Options::="--force-confdef" '
            '-o Dpkg::Options::="--force-confold" --force-yes'
        )

    @uses_fabric
    def add_ppa(self, name):
        """Add personal package archive."""

        if self.ubuntu_release >= Decimal("12.04"):
            sudo("apt-add-repository -y %s" % name)
        else:
            sudo("apt-add-repository %s" % name)
        self.update_apt_sources()

    @uses_fabric
    def add_aptrepo(self, url, dist, repo_name, key_name=None, key_server=None):
        repo = " ".join(["deb", url, dist, repo_name])
        files.append("/etc/apt/sources.list", repo, use_sudo=True)
        if key_server is None:
            key_server = "keyserver.ubuntu.com"
        if key_name:
            sudo("apt-key adv --keyserver {0} --recv {1}".format(key_server, key_name))
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
        new_class = super(AptMixinMetaclass, cls).__new__(cls, name, bases, attrs)
        new_class._package_names = set(
            [b.package_name for b in bases if hasattr(b, "package_name")]
        )
        if "package_name" in attrs:
            new_class._package_names.add(attrs["package_name"])
        return new_class


class AptMixin(BaseAptMixin, metaclass=AptMixinMetaclass):
    def setup(self, propagate=True):
        super(AptMixin, self).setup()
        for attr_prefix in self._package_names:
            ppa = getattr(self, "%s_ppa" % attr_prefix, None)
            aptrepo = getattr(self, "%s_aptrepo" % attr_prefix, None)
            packages = getattr(self, "%s_packages" % attr_prefix, [])
            if ppa:
                self.add_ppa(ppa)
            if aptrepo:
                self.add_aptrepo(*aptrepo)
            self.install_packages(packages)
