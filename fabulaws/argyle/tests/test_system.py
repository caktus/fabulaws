import os

from fabric.api import settings
from mock import patch

from .utils import unittest, ArgyleTest
from argyle import system


class SystemTest(ArgyleTest):
    "Base for setting up necessary patches."

    package = 'argyle.system'
    patched_commands = ['run', 'sudo', 'put', 'files', ]


class PackageCommandsTest(SystemTest):
    "Package management (install, update, etc) commands."

    def test_install_single_package(self):
        "Install a single package throuh apt."
        system.install_packages('python')
        self.assertSudoCommand('apt-get install -y python')

    def test_install_multiple_packages(self):
        "Install multiple packages through apt."
        system.install_packages('python', 'python-setuptools')
        self.assertSudoCommand('apt-get install -y python python-setuptools')

    def test_install_from_file(self):
        "Install packages from a file."
        path = os.path.join(os.path.dirname(__file__), 'data/packages.txt')
        system.install_packages_from_file(path)
        self.assertSudoCommand('apt-get install -y python python-setuptools')

    def test_upgrade_packages(self):
        "Call apt-get upgrade."
        system.upgrade_apt_packages()
        self.assertSudoCommand('apt-get upgrade -y')

    def test_update_package_sources(self):
        "Call apt-get update."
        system.update_apt_sources()
        self.assertSudoCommand('apt-get update')

    def test_add_ppa(self):
        "Add PPA and refresh apt-sources."
        with patch('argyle.system.update_apt_sources') as update:
            system.add_ppa('ppa:nginx/stable')
            self.assertSudoCommand('add-apt-repository ppa:nginx/stable')
            self.assertTrue(update.called)

    def test_add_ppa_no_update(self):
        "Add PPA without updating sources."
        with patch('argyle.system.update_apt_sources') as update:
            system.add_ppa('ppa:nginx/stable', update=False)
            self.assertSudoCommand('add-apt-repository ppa:nginx/stable')
            self.assertFalse(update.called)

    def test_add_ppas_from_file(self):
        "Add PPAs from file list."
        path = os.path.join(os.path.dirname(__file__), 'data/ppas.txt')
        with patch('argyle.system.update_apt_sources') as update:
            with patch('argyle.system.add_ppa') as add_ppa:
                system.add_ppas_from_file(path)
                self.assertEqual(add_ppa.call_count, 2)
                self.assertEqual(update.call_count, 1)

    def test_add_apt_source_no_key(self):
        "Add apt souce without key url."
        with patch('argyle.system.update_apt_sources') as update:
            system.add_apt_source("deb http://example.com/deb lucid main")
            # Source file should be backed up
            self.assertSudoCommand('cp /etc/apt/sources.list{,.bak}')
            files = self.mocks['files']
            self.assertTrue(files.append.called)
            args, kwargs = files.append.call_args
            source_list = args[0]
            new_source = args[1]
            self.assertEqual(source_list, '/etc/apt/sources.list')
            self.assertEqual(new_source, 'deb http://example.com/deb lucid main')
            # Apt sources should be updated
            self.assertTrue(update.called)

    def test_add_apt_source_no_update(self):
        "Add apt souce without updating apt sources."
        with patch('argyle.system.update_apt_sources') as update:
            system.add_apt_source("deb http://example.com/deb lucid main", update=False)
            # Apt sources should not be updated
            self.assertFalse(update.called)

    def test_add_apt_source_with_key(self):
        "Add apt souce with key url."
        with patch('argyle.system.update_apt_sources') as update:
            source = "deb http://example.com/deb lucid main"
            key = "http://example.com/key"
            system.add_apt_source(source, key)
            # Key file should be added
            self.assertSudoCommand('wget -q http://example.com/key -O - | sudo apt-key add -')
            files = self.mocks['files']
            self.assertTrue(files.append.called)
            args, kwargs = files.append.call_args
            source_list = args[0]
            new_source = args[1]
            self.assertEqual(source_list, '/etc/apt/sources.list')
            self.assertEqual(new_source, source)
            # Apt sources should be updated
            self.assertTrue(update.called)

    def test_add_apt_sources_from_file(self):
        "Add a list of apt sources from a file."
        path = os.path.join(os.path.dirname(__file__), 'data/sources.txt')
        with patch('argyle.system.update_apt_sources') as update:
            with patch('argyle.system.add_apt_source') as add_source:
                system.add_sources_from_file(path)
                self.assertEqual(add_source.call_count, 2)
                self.assertEqual(update.call_count, 1)


class UserCommandsTest(SystemTest):
    "User/group creation and existance tests."

    def test_user_exists_command(self):
        "Check if a user exists by checking /etc/passwd."
        system.user_exists('postgres')
        self.assertRunCommand('grep ^postgres /etc/passwd')

    def test_user_exists_value(self):
        "user_exists return value should depend on the result of grep."
        run = self.mocks['run']
        run.return_value = True
        self.assertTrue(system.user_exists('postgres'))
        run.return_value = False
        self.assertFalse(system.user_exists('postgres'))
        
    def test_group_exists_command(self):
        "Check if a group exists by checking /etc/group."
        system.group_exists('admin')
        self.assertRunCommand('grep ^admin /etc/group')

    def test_group_exists_value(self):
        "group_exists return value should depend on the result of grep."
        run = self.mocks['run']
        run.return_value = True
        self.assertTrue(system.group_exists('admin'))
        run.return_value = False
        self.assertFalse(system.group_exists('admin'))

    def test_simple_create_user(self):
        "Create new user without any groups."
        with patch('argyle.system.user_exists') as exists:
            exists.return_value = False
            system.create_user('foo')
            # Create user
            self.assertSudoCommand('useradd -m  -s /bin/bash foo')
            # Disable password
            self.assertSudoCommand('passwd -d foo')

    def test_user_already_exists(self):
        "Don't try to create users which already exist."
        with patch('argyle.system.user_exists') as exists:
            exists.return_value = True
            system.create_user('foo')
            sudo = self.mocks['sudo']
            self.assertFalse(sudo.called)

    def test_create_user_with_new_groups(self):
        "Create groups which don't exist and add the user to them."
        with patch('argyle.system.user_exists') as user_exists:
            with patch('argyle.system.group_exists') as group_exists:
                user_exists.return_value = False
                group_exists.return_value = False
                system.create_user('foo', groups=['admin', 'ssh'])
                # Create groups
                self.assertSudoCommand('addgroup admin')
                self.assertSudoCommand('addgroup ssh')
                # Create user
                self.assertSudoCommand('useradd -m -G admin,ssh -s /bin/bash foo')
        
    def test_create_user_with_existing_groups(self):
        "No need to create groups which already exist."
        with patch('argyle.system.user_exists') as user_exists:
            with patch('argyle.system.group_exists') as group_exists:
                user_exists.return_value = False
                group_exists.return_value = True
                system.create_user('foo', groups=['admin', 'ssh'])
                # Create groups
                self.assertNoSudoCommand('addgroup admin')
                self.assertNoSudoCommand('addgroup ssh')
                # Create user
                self.assertSudoCommand('useradd -m -G admin,ssh -s /bin/bash foo')

    def test_create_user_with_key_file(self):
        "Create a user and push a key file to the remote."
        key_file = 'foo/key.pub'
        with patch('argyle.system.user_exists') as exists:
            exists.return_value = False
            system.create_user('foo', key_file=key_file)
            # Create remote ssh directory and set permissions
            self.assertSudoCommand('mkdir -p /home/foo/.ssh')
            self.assertSudoCommand('chown -R foo:foo /home/foo/.ssh')
            put = self.mocks['put']
            self.assertTrue(put.called)
            args, kwargs = put.call_args
            file_name, remote_path = args
            self.assertEqual(file_name, key_file)
            self.assertEqual(remote_path, '/home/foo/.ssh/authorized_keys')


class ServiceCommandsTest(SystemTest):
    "Commands for starting/stoping services."

    def test_default_service_command(self):
        "Default start/stop via init.d."
        system.service_command('nginx', 'start')
        self.assertSudoCommand('/etc/init.d/nginx start')
        
    def test_service_command_template(self):
        "Change how commands are called via ARGYLE_SERVICE_COMMAND_TEMPLATE."
        with settings(ARGYLE_SERVICE_COMMAND_TEMPLATE="invoke-rc.d %(name)s %(command)s"):
            system.service_command('nginx', 'start')
            self.assertSudoCommand('invoke-rc.d nginx start')
        
    def test_start_service(self):
        "Start is thin wrappers around service_command."
        with patch('argyle.system.service_command') as service_command:
            system.start_service('nginx')
            self.assertTrue(service_command.called)
            args, kwargs = service_command.call_args
            self.assertEqual(list(args), ['nginx', 'start'])

    def test_stop_service(self):
        "Stop is thin wrappers around service_command."
        with patch('argyle.system.service_command') as service_command:
            system.stop_service('nginx')
            self.assertTrue(service_command.called)
            args, kwargs = service_command.call_args
            self.assertEqual(list(args), ['nginx', 'stop'])

    def test_restart_service(self):
        "Restart is thin wrappers around service_command."
        with patch('argyle.system.service_command') as service_command:
            system.restart_service('nginx')
            self.assertTrue(service_command.called)
            args, kwargs = service_command.call_args
            self.assertEqual(list(args), ['nginx', 'restart'])


if __name__ == '__main__':
    unittest.main()
