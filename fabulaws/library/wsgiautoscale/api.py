from __future__ import absolute_import

import os
import sys
import time
import random
import string
import logging
import datetime
import multiprocessing
from runpy import run_path

import subprocess
from tempfile import mkstemp

import yaml

from getpass import getpass

from boto.ec2.elb import ELBConnection
from boto.ec2.autoscale import AutoScaleConnection, LaunchConfiguration, Tag
from boto.exception import BotoServerError

from fabric.api import (abort, cd, env, execute, hide, hosts, local, parallel,
    prompt, put, roles, require, run, runs_once, settings, sudo, task)
from fabric.colors import red
from fabric.contrib.files import exists, upload_template, append, uncomment, sed
from fabric.exceptions import NetworkError
from fabric.network import disconnect_all

from argyle import system
from argyle.supervisor import supervisor_command

from fabulaws.api import answer_sudo, ec2_instances, sshagent_run

from .servers import (CacheInstance, DbPrimaryInstance,
    DbReplicaInstance, WebInstance, WorkerInstance,
    CombinedInstance)


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def _reset_hosts():
    """Reset the roledefs and servers environment variables to their default values."""
    # roledefs must be defined, even with empty lists, for Fabric to run
    env.roledefs = dict((role, []) for role in env.valid_roles)
    env.servers = dict((role, []) for role in env.valid_roles)

# Mapping of Fabric roles to FabulAWS server class names
env.role_class_map = {
    'cache': CacheInstance,
    'db-primary': DbPrimaryInstance,
    'db-replica': DbReplicaInstance,
    'web': WebInstance,
    'worker': WorkerInstance,
    'combo': CombinedInstance,
}

config_file = 'fabulaws-config.yml'
config = yaml.load(file(config_file, 'r'))
for key, value in config.items():
    setattr(env, key, value)
_reset_hosts()
PROJECT_ROOT = os.path.dirname(__file__)
env.templates_dir = os.path.join(PROJECT_ROOT, 'templates')
# expand absolute paths for all config-relative directories
for key, value in env.static_html.items():
    env.static_html[key] = os.path.join(os.path.abspath(os.path.dirname(config_file)), value)
for key in ['ssh_keys', 'localsettings_template']:
    new_path = os.path.join(os.path.abspath(os.path.dirname(config_file)), getattr(env, key))
    setattr(env, key, new_path)

def _get_servers(deployment, environment, role, instance_ids=None):
    """
    Queries EC2 and returns the list of FabulAWS server instances for the given
    deployment, environment, and role.
    """
    env.filters = {'tag:environment': environment,
                   'tag:deployment': deployment,
                   'tag:role': role}
    inst_kwargs = {
        'instance_type': _find(env.instance_types, environment, role),
        'volume_size': _find(env.volume_sizes, environment, role),
        'volume_type': _find(env.volume_types, environment, role),
        'security_groups': _find(env.security_groups, environment, role),
        'deploy_user': env.deploy_user,
        'deploy_user_home': env.home,
    }
    inst_kwargs.update(env.instance_settings)
    return ec2_instances(filters=env.filters, cls=env.role_class_map[role],
                         inst_kwargs=inst_kwargs, instance_ids=instance_ids)


def _find(dict_, key1, key2):
    """
    Searches dict_ for keys in the following order:

    (key1, key2)
    (key1)
    (key2)

    The resulting value is returned.
    """
    if key1 in dict_:
        if isinstance(dict_[key1], dict):
            return dict_[key1][key2]
        return dict_[key1]
    elif key2 in dict_:
        return dict_[key2]
    else:
        raise ValueError('No combination of (%s, %s) found in %s!' % (key1, key2, dict_))


def _setup_env(deployment_tag=None, environment=None, override_servers={}):
    """
    Sets up paths and other configuration in the ``env`` dictionary necessary
    for running Fabric commands.
    """
    if deployment_tag is not None:
        env.deployment_tag = deployment_tag
    if environment is not None:
        env.environment = environment
    env.root = os.path.join(env.home, 'www', env.environment)
    env.log_dir = os.path.join(env.root, 'log')
    env.code_root = os.path.join(env.root, 'code_root')
    env.project_root = os.path.join(env.code_root, env.project)
    env.virtualenv_root = os.path.join(env.root, 'env')
    env.media_root = os.path.join(env.root, 'uploaded_media')
    env.static_root = os.path.join(env.root, 'static_media')
    env.services = os.path.join(env.home, 'services')
    env.nginx_conf = os.path.join(env.services, 'nginx', '%s.conf' % env.environment)
    env.local_settings_py = os.path.join(env.project_root, 'local_settings.py')
    env.database_name = '%s_%s' % (env.project, env.environment)
    env.staticfiles_s3_bucket = '-'.join([env.deployment_tag, env.environment, 'static', 'files'])
    env.site_domains = env.site_domains_map[env.environment]
    assert all([bool(domain) for domain in env.site_domains]) and len(env.site_domains) > 0,\
           'need at least one site domain for %s' % env.environment
    env.vhost = '%s_%s' % (env.project, env.environment)
    env.branch = _find(env.branches, env.deployment_tag, env.environment)
    env.elb_names = _find(env.load_balancers, env.deployment_tag, env.environment)
    env.ag_name = _find(env.auto_scaling_groups, env.deployment_tag, env.environment)
    env.server_port = env.server_ports[env.environment]
    env.gpg_dir = os.path.join(env.home, 'backup-info', 'gnupg')
    env.pgpass_file = os.path.join(env.home, 'backup-info', 'pgpass')
    for role in env.valid_roles:
        if role in override_servers:
            servers = override_servers[role]
        else:
            servers = _get_servers(env.deployment_tag, env.environment, role)
        hostnames = [server.hostname for server in servers]
        # limit hostnames and roles to the given hosts (e.g., if passed on the command line)
        if set(hostnames) & set(env.hosts):
            hostnames = env.hosts
            servers = [s for s in servers if s.hostname in hostnames]
            env.roles.append(role)
        env.roledefs[role] = hostnames
        env.servers[role] = servers
        # combo instances also fulfill the db-primary and web roles
        if role == 'combo':
            env.roledefs['db-primary'].extend(hostnames)
            env.servers['db-primary'].extend(servers)
            env.roledefs['web'].extend(hostnames)
            env.servers['web'].extend(servers)
            env.roledefs['worker'].extend(hostnames)
            env.servers['worker'].extend(servers)
    if not env.roles:
        env.roles = env.valid_roles
    try:
        env.cache_server = env.servers['cache'][0]
    except IndexError:
        env.cache_server = None
    try:
        env.master_database = env.servers['db-primary'][0]
        env.master_database.database_key = 'default'
        env.master_database.database_local_name = env.database_name
    except IndexError:
        env.master_database = None
    env.slave_databases = []
    for i, server in enumerate(env.servers['db-replica']):
        server.database_key = 'replica%s' % i
        server.database_local_name = '_'.join([env.database_name, server.database_key])
        env.slave_databases.append(server)
    env.all_databases = []
    if env.master_database:
        env.all_databases.append(env.master_database)
    env.all_databases.extend(env.slave_databases)
    for i, db in enumerate(env.all_databases):
        db.stunnel_port = 7432 + i
    env.db_settings = env.get('db_settings', {})
    env.setdefault('gelf_log_host', False)
    if hasattr(env, 'log_host'):
        print(red("Warning: Setting log_host is deprecated. Set gelf_log_host "
                  "instead".format(environment=env.environment),
              bold=True))
        if env.log_host and not env.gelf_log_host:
            env.gelf_log_host = env.log_host
    env.setdefault('syslog_server', False)
    env.setdefault('awslogs_access_key_id', False)
    if 'production_environments' not in env:
        # Backwards compatibility
        env.production_environments = ['production']
    if 'use_basic_auth' not in env:
        env.use_basic_auth = {}
    env.setdefault('extra_log_files', {})
    env.log_files = [
        ('munin', '/var/log/munin/munin-node.log', '%Y/%m/%d-%H:%M:%S'),
        ('postgresql', '/var/log/postgresql/postgresql-*.log', '%Y-%m-%d %H:%M:%S'),
        ('redis', '/var/log/redis/redis*.log', '%d %b %H:%M:%S'),
        ('rabbitmq', '/var/log/rabbitmq/rabbit*.log', '%d-%b-%Y::%H:%M:%S'),
        ('nginx', os.path.join(env.log_dir, 'error.log'), '%Y/%m/%d %H:%M:%S'),
        ('nginx', os.path.join(env.log_dir, 'access.log'), '%Y/%m/%d %H:%M:%S'),
        ('gunicorn', os.path.join(env.log_dir, 'gunicorn.log'), '%Y-%m-%d %H:%M:%S'),
        ('pgbouncer', os.path.join(env.log_dir, 'pgbouncer.log'), '%Y-%m-%d %H:%M:%S'),
        ('stunnel', os.path.join(env.log_dir, 'stunnel.log'), '%Y-%m-%d %H:%M:%S'),
        ('celery', os.path.join(env.log_dir, 'celerycam.log'), '%Y-%m-%d %H:%M:%S'),
        ('celery', os.path.join(env.log_dir, 'celerybeat.log'), '%Y-%m-%d %H:%M:%S'),
    ]
    # add celery logs, based on the workers configured in fabulaws-config.yaml
    env.log_files += [
        ('celery', os.path.join(env.log_dir, 'celeryd-%s.log' % w), '%Y-%m-%d %H:%M:%S')
         for w in env.celery_workers.keys()
    ]
    # add any extra_log_files configured in fabulaws-config.yaml
    env.log_files += [
        (args['tag'], filepath, args.get('date_format', ''))
        for filepath, args in env.extra_log_files.items()
    ]


def _read_local_secrets():
    """
    Return a dictionary with the secrets from the local secrets file, if any;
    else returns None.
    """
    secrets_files = [
        'fabsecrets_{environment}.py'.format(environment=env.environment),
        'fabsecrets.py'
    ]
    secrets_file = None
    for filename in secrets_files:
        if os.path.exists(filename):
            secrets_file = filename
            break
    else:
        print(red("Warning: No secrets file found. Looked for %r" % secrets_files, bold=True))
        return None
    if secrets_file == 'fabsecrets.py':
        print(red("Warning: Getting secrets from fabsecrets.py, which is deprecated. Secrets "
                  "should be in fabsecrets_{environment}.py.".format(environment=env.environment),
                  bold=True))
    secrets = run_path(secrets_file)
    # run_path returns the globals dictionary, which includes things
    # like __file__, so strip those out.
    secrets = {k: secrets[k] for k in secrets if not k.startswith("__")}
    return secrets


def _random_password(length=8, chars=string.letters + string.digits):
    """Generates a random password with the specificed length and chars."""
    return ''.join([random.choice(chars) for i in range(length)])


def _load_passwords(names, ignore_local=False):
    """
    Utility for working with secrets, maybe on a remote server.

    It gets a value for each password: If there's a local secrets file and it
    has a value for name and ignore_local is false, it uses the
    value from the local secrets file; in all other cases, it gets
    the value from the remote server.

    Then it sets the password as an attribute on 'env'.  This is because template rendering
    uses `env` as its context and all the templates expect the
    passwords to be in the context.

    :param names: Iterable of names to operate on
    :param ignore_local: Whether to prefer the remote value even if there's a local value
    """
    if ignore_local:
        fabsecrets = None
    else:
        fabsecrets = _read_local_secrets()
    for name in names:
        filename = os.path.join(env.home, name)
        if fabsecrets and name in fabsecrets and not ignore_local:
            passwd = fabsecrets[name]
        elif env.host_string and exists(filename):
            with hide('stdout'):
                passwd = sudo('cat %s' % filename).strip()
        else:
            passwd = getpass('Please enter %s: ' % name)
        setattr(env, name, passwd)


def _instance_name(*args):
    """Generates an EC2 instance name based on the deployment, environment, and role."""
    return '_'.join([env.deployment_tag, env.environment] + list(args))


def _current_roles():
    """Returns a list of roles for the current env.host_string."""
    roles = []
    for role, roledef in env.roledefs.items():
        if env.host_string in roledef:
            roles.append(role)
    return roles


def _current_server():
    """Returns the Fabulaws server instance with the current env.host_string."""
    # If we're inside a fabulaws context manager, return that server.
    if getattr(env, 'current_server', None):
        return env.current_server

    # Otherwise, discover the server based on the host name.
    for role, servers in env.servers.items():
        for s in servers:
            if s.hostname == env.host_string:
                return s


def _allowed_hosts():
    """Returns the allowed hosts that should be set for the current server."""
    server = _current_server()
    # Filter out None or '' (e.g., if the instance doesn't have a public IP)
    server_addrs = filter(lambda addr: bool(addr), [
        server.instance.private_dns_name,
        server.instance.private_ip_address,
        server.instance.public_dns_name,
        server.instance.ip_address,
    ])
    return env.site_domains + server_addrs


def _change_role(server, new_role):
    """Update the role (and name) of the given server."""
    print 'Changing role for %s (%s) to %s' % (server.hostname, server.instance.id, new_role)
    server.add_tags({
        'role': new_role,
        'Name': _instance_name(new_role),
    })


def _stop_all():
    """Stop all supervisor services, in order."""
    executel('supervisor', 'stop', 'web', roles=['web'])
    executel('supervisor', 'stop', 'celery', roles=['worker'])
    executel('supervisor', 'stop', 'pgbouncer')


def _start_all():
    """Start all supervisor services, in order."""
    executel('supervisor', 'start', 'pgbouncer')
    executel('supervisor', 'start', 'celery', roles=['worker'])
    executel('supervisor', 'start', 'web', roles=['web'])


def _check_local_deps():
    """verify local dependencies exist."""
    with settings(warn_only=True):
        curl = local('which curl')
    if curl.failed:
        abort('You must install curl to run a deployment.')

###### ENVIRONMENT SETUP ######

def _is_production(environment):
    """
    Return True if the environment named 'environment' appears to
    be a production environment.

    If the config has an item named 'production_environments', then it is
    taken as a list of environment names that are production environments, and
    everything else is assumed not to be production.

    If there is no such configuration item, _setup_env (above) defaults
    it to just ['production'].
    """
    return environment in env.production_environments


@task
def testing(deployment_tag=env.default_deployment, answer=None): # support same args as production
    _setup_env(deployment_tag, 'testing')


@task
def staging(deployment_tag=env.default_deployment, answer=None): # support same args as production
    _setup_env(deployment_tag, 'staging')


@task
def production(deployment_tag=env.default_deployment, answer=None):
    if answer is None:
        answer = prompt('Are you sure you want to activate the production '
                        'environment?', default='n')
    if answer != 'y':
        abort('Production environment not activated.')
    _setup_env(deployment_tag, 'production')


@task
def call_server_method(method):
    server = _current_server()
    roles = _current_roles()
    print '\n *** calling {0} on {1} ({2}) ***\n'.format(method, server.hostname, roles[0])
    getattr(server, method)()


@task
def run_shell_command(method, sudo=False):
    server = _current_server()
    roles = _current_roles()
    print '\n *** calling {0} on {1} ({2}) ***\n'.format(method, server.hostname, roles[0])
    if sudo:
        sudo(method)
    else:
        run(method)


###### NEW SERVER SETUP ######


def _new(deployment, environment, role, avail_zone=None, count=1, terminate_on_failure=False, **kwargs):
    """ create new server on AWS using the given deployment, environment, and role """
    if deployment not in env.deployments:
        abort('Choose a valid deployment: %s' % ', '.join(env.deployments))
    if environment not in env.environments:
        abort('Choose a valid environment: %s' % ', '.join(env.environments))
    if role not in env.valid_roles:
        abort('Choose a valid role: %s' % ', '.join(env.valid_roles))
    if avail_zone and avail_zone not in env.avail_zones:
        abort('Choose a valid availability zone: %s' % ', '.join(env.avail_zones))
    env.hosts = []
    env.deployment_tag = deployment
    env.environment = environment
    env.roles = [role]
    count = int(count)
    tags = {
        'environment': env.environment,
        'deployment': env.deployment_tag,
        'role': role + '-PENDING', # don't add servers to this role until they're fully created (below)
        'Name': _instance_name(role + '-PENDING'),
    }
    if not avail_zone:
        avail_zone = random.choice(env.avail_zones)
        print 'Note: Assigning random availability zone "{0}"'.format(avail_zone)
    placement = ''.join([env.region, avail_zone])
    _setup_env()
    # copy the original so we don't accidentally store luks_passphrase on the server
    password_names = list(env.password_names)
    if env.instance_settings['fs_encrypt']:
        password_names.append('luks_passphrase')
    _load_passwords(password_names)
    servers = []
    for x in range(count):
        type_ = _find(env.instance_types, env.environment, role)
        cls = env.role_class_map[role]
        vol_size = _find(env.volume_sizes, environment, role)
        vol_type = _find(env.volume_types, environment, role)
        sec_grps = _find(env.security_groups, environment, role)
        extra_args = kwargs.copy()
        extra_args.update(env.instance_settings)
        server = cls(instance_type=type_, placement=placement, deploy_user_home=env.home,
                     tags=tags, volume_size=vol_size, volume_type=vol_type,
                     deploy_user=env.deploy_user, security_groups=sec_grps,
                     **extra_args)
        try:
            server.setup()
        except:
            logger.exception('server.setup() failed. tags=%s; terminate_on_failure=%s.',
                             tags, terminate_on_failure)
            if terminate_on_failure:
                server.terminate()
            raise
        servers.append(server)
    # the methods below should only be run on the created server(s), so
    # replace that role definition accordingly
    saved_roledefs = env.roledefs[role]
    saved_servers = env.servers[role]
    try:
        env.roledefs[role] = [server.hostname for server in servers]
        env.servers[role] = servers
        executel('update_server_passwords', hosts=env.roledefs[role])
        executel('install_munin', hosts=env.roledefs[role])
        if env.gelf_log_host:
            executel('install_logstash', hosts=env.roledefs[role])
        if env.syslog_server:
            executel('install_rsyslog', hosts=env.roledefs[role])
        if env.awslogs_access_key_id:
            executel('install_awslogs', hosts=env.roledefs[role])
        if role in ('worker', 'web'):
            executel('bootstrap', hosts=env.roledefs[role])
    except:
        logger.exception('server post-setup failed. tags=%s; terminate_on_failure=%s.',
                         tags, terminate_on_failure)
        if terminate_on_failure:
            for server in servers:
                server.terminate()
        raise
    finally:
        env.roledefs[role] = saved_roledefs
        env.servers[role] = saved_servers
    # now that the servers have been created, give them the correct role
    for server in servers:
        _change_role(server, role)
    return servers


class RetryFailure(Exception):
    """To be used as env.abort_exception in Fabric."""
    pass


def _retry_new(*args, **kwargs):
    """
    Retries instance creation up to three times (or ``tries``, if supplied).
    Helps circumvent temporary network failures (e.g., while running apt-get).
    """
    tries = kwargs.pop('tries', 3)
    with settings(abort_exception=RetryFailure, abort_on_prompts=True):
        for i in range(tries - 1):
            try:
                return _new(*args, terminate_on_failure=True, **kwargs)
            # Fabric may raise our abort_exception OR a NetworkError
            except (RetryFailure, NetworkError):
                print '\n\n **** Server creation failed; retrying (attempt #%s)... ****\n\n' % (i+2)
                continue
    # if the last attempt is still going to fail, let it fail normally:
    return _new(*args, **kwargs)


class BackgroundCommand(multiprocessing.Process):
    """
    Multiprocessing Process class to run a method in the background
    (with logging to a file) and save the result.
    """

    def __init__(self, func, args=None, capture_result=False):
        super(BackgroundCommand, self).__init__()
        self.func = func
        self.args = args or []
        self.capture_result = capture_result
        self.queue = multiprocessing.Queue()

    def run(self):
        date = datetime.datetime.now().strftime('%Y-%m-%d_%H:%M:%S')
        filename = '_'.join([date] + list(self.args[1:]) + [str(os.getpid())]) + ".out"
        print 'Starting log file %s' % filename
        # redirect stdout to a log file
        sys.stdout = open(filename, "w")
        sys.stderr = sys.stdout
        # reset logging handler to point to the new stdout
        root_logger = logging.getLogger()
        root_logger.handlers = []
        root_logger.addHandler(logging.StreamHandler(stream=sys.stdout))
        result = self.func(*self.args)
        if self.capture_result and result is not None:
            self.queue.put(result)

    def result(self):
        if not self.capture_result:
            raise Exception('Must pass capture_result=True to __init__ before calling result()')
        if not hasattr(self, '_result'):
            self._result = self.queue.get()
        return self._result


def _create_many(servers):
    """Create many servers at once, in parallel."""
    procs = []
    print 'Creating servers in parallel; see individual log files for progress...'
    # make sure we don't pass open SSH connections down to the child procs
    disconnect_all()
    for server in servers:
        proc = BackgroundCommand(_retry_new, args=list(server))
        proc.start()
        procs.append(proc)
    time.sleep(2)
    print 'Waiting for servers to be created...'
    for proc in procs:
        proc.join()
        if proc.exitcode != 0:
            abort('Server creation failed for: %s. Inspect the appropriate log file.' % proc.args)
    print 'Done.'


@task
def new(deployment, environment, role, avail_zone=None, count=1):
    _new(deployment, environment, role, avail_zone, count)


def vcs(cmd, args=None):
    # vcs commands assume hg, so convert 'update' to 'checkout' if needed
    if cmd == 'update' and env.vcs_cmd.endswith('git'):
        cmd = 'checkout'
    if args is None:
        args = []
    parts = [env.vcs_cmd, cmd] + args
    if cmd in ('pull', 'clone'):
        ssh_cmd = 'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'
        if env.vcs_cmd.endswith('hg'):
            parts.append('-e "%s"' % ssh_cmd)
        elif env.vcs_cmd.endswith('git'):
            sudo('mkdir -p %s/.ssh' % env.home, user=env.deploy_user)
            sudo('touch %s/.ssh/options' % env.home, user=env.deploy_user)
            append('%s/.ssh/config' % env.home, 'UserKnownHostsFile=/dev/null', use_sudo=True)
            append('%s/.ssh/config' % env.home, 'StrictHostKeyChecking=no', use_sudo=True)
            #parts.insert(0, 'GIT_SSH_COMMAND="%s"' % ssh_cmd)
    if cmd == 'pull' and env.vcs_cmd.endswith('git'):
        # git forgets which branch it was on after checking out a specific revision,
        # so remind it here (update_source calls 'checkout' with the correct
        # revision immediately after running 'pull')
        parts.append('origin %s' % env.branch)
    sshagent_run(' '.join(parts), user=env.deploy_user)


@task
@runs_once
@roles('worker')
def update_local_fabsecrets():
    """ create or update the local fabsecrets_<environment>.py file based on the passwords on the server """

    require('environment', provided_by=env.environments)

    local_path = os.path.abspath('fabsecrets_{environment}.py'.format(environment=env.environment))

    if os.path.exists(local_path):
        answer = prompt('Are you sure you want to destroy %s '
                        'and replace it with a copy of the values from '
                        'the worker on %s?'
                        '' % (local_path, env.environment.upper()), default='n')
        if answer != 'y':
            abort('Aborted.')

    # Get the secrets from the remote server, ignoring any local secrets since we want
    # to replace them with the ones actually in use.
    _load_passwords(env.password_names, ignore_local=True)
    out = ''
    for p in env.password_names:
        out += '%s = "%s"\n' % (p, getattr(env, p))
    with open(local_path, 'w') as f:
        f.write(out)
    print("Wrote passwords to %s" % local_path)


@task
@parallel
@roles('web', 'worker')
def clone_repo():
    """ clone a new copy of the code repository """

    with cd(env.root):
        vcs('clone', [env.repo, env.code_root])
    with cd(env.code_root):
        vcs('update', [env.branch])


@task
@parallel
@roles('web', 'worker')
def setup_dirs():
    """ create (if necessary) and make writable uploaded media, log, etc. directories """

    require('environment', provided_by=env.environments)
    sudo('mkdir -p %(log_dir)s' % env, user=env.deploy_user)
    sudo('chmod a+w %(log_dir)s' % env )
    sudo('mkdir -p %(services)s/nginx' % env, user=env.deploy_user)
    sudo('mkdir -p %(services)s/nginx/html' % env, user=env.deploy_user)
    sudo('mkdir -p %(services)s/supervisor' % env, user=env.deploy_user)
    sudo('mkdir -p %(services)s/pgbouncer' % env, user=env.deploy_user)
    sudo('mkdir -p %(services)s/stunnel' % env, user=env.deploy_user)
    sudo('mkdir -p %(media_root)s' % env)
    sudo('mkdir -p %(static_root)s' % env)
    # Web server needs to be able to create files under media
    # We also use the web server user when running manage.py commands
    # like collectstatic, so static_root needs to be owned by it too.
    sudo('chown -R %(webserver_user)s %(media_root)s %(static_root)s' % env)


def _upload_template(filename, destination, **kwargs):
    """Upload template and chown to given user"""
    user = kwargs.pop('user')
    kwargs['use_sudo'] = True
    upload_template(filename, destination, **kwargs)
    sudo('chown %(user)s:%(user)s %(dest)s' % {'user': user, 'dest': destination})


@task
@parallel
@roles('web', 'worker')
def upload_supervisor_conf(run_update=True):
    """Upload Supervisor configuration from the template."""

    require('environment', provided_by=env.environments)
    destination = os.path.join(env.services, 'supervisor', '%(environment)s.conf' % env)
    context = env.copy()
    cpu_count = int(run('cat /proc/cpuinfo|grep processor|wc -l'))
    context['timeout'] = int(getattr(env, 'gunicorn_timeout', 30))
    context['worker_class'] = getattr(env, 'gunicorn_worker_class', 'sync')
    context['worker_count'] = cpu_count * int(getattr(env, 'gunicorn_worker_multiplier', 4))
    context['current_role'] = _current_roles()[0]
    _upload_template('supervisor.conf', destination, context=context,
                     user=env.deploy_user, use_jinja=True,
                     template_dir=env.templates_dir)
    with settings(warn_only=True):
        sudo('rm /etc/supervisor/conf.d/%(project)s-*.conf' % env)
    sudo('ln -s /%(home)s/services/supervisor/%(environment)s.conf /etc/supervisor/conf.d/%(project)s-%(environment)s.conf' % env)
    if run_update:
        supervisor_command('update')


@task
@parallel
@roles('web', 'worker')
def upload_pgbouncer_conf():
    """Upload Supervisor configuration from the template."""

    require('environment', provided_by=env.environments)
    env.database_server = None
    _load_passwords(['database_password'])
    # pgbouncer users
    destination = os.path.join(env.services, 'pgbouncer',
                               'pgbouncer-users.txt')
    _upload_template('pgbouncer-users.txt', destination, context=env,
                     user=env.deploy_user, use_jinja=True,
                     template_dir=env.templates_dir)
    # stunnel config
    destination = os.path.join(env.services, 'stunnel',
                               '{0}.conf'.format(env.environment))
    _upload_template('stunnel.conf', destination, context=env,
                     user=env.deploy_user, use_jinja=True,
                     template_dir=env.templates_dir)
    # pgbouncer config
    destination = os.path.join(env.services, 'pgbouncer',
                               'pgbouncer-{0}.ini'.format(env.environment))
    _upload_template('pgbouncer.ini', destination, context=env,
                     user=env.deploy_user, use_jinja=True,
                     template_dir=env.templates_dir)


@task
@parallel
@roles('web')
def upload_nginx_conf():
    """Upload Nginx configuration from the template."""

    require('environment', provided_by=env.environments)
    _load_passwords(env.password_names)
    context = dict(env)
    context['allowed_hosts'] = []
    context['passwdfile_path'] = ''
    # transform Django's ALLOWED_HOSTS into a format acceptable by Nginx (see
    # http://nginx.org/en/docs/http/server_names.html and
    # http://nginx.org/en/docs/http/request_processing.html)
    for sn in _allowed_hosts():
        if sn.endswith('.'):
            sn = sn[:-1]
        if sn.startswith('.'):
            # A rough approximation of RFC 1123: hostnames may contain letters,
            # digits, and hyphens. For some reason, Nginx's '*' wildcard allows
            # bogus hostnames like '*.example.com' through to Django.
            # Specifying a regular expression instead prevents that.
            sn = r'"~[a-zA-Z0-9-]+%s$"' % sn.replace('.', r'\.')
        context['allowed_hosts'].append(sn)
    if env.use_basic_auth.get(env.environment):
        (handle, tmpfile) = mkstemp()
        f = os.fdopen(handle, 'w')
        cmd = ['openssl', 'passwd', '-apr1', env.basic_auth_password]
        encrypted = subprocess.check_output(cmd)
        f.write(env.basic_auth_username + ":" + encrypted + "\n")
        f.close()
        context['passwdfile_path'] = "/etc/nginx/%(project)s.passwd" % env
        template_dir = os.path.dirname(tmpfile)
        template_name = os.path.basename(tmpfile)
        _upload_template(template_name, context['passwdfile_path'], context=context, user='root',
                         use_jinja=True, template_dir=template_dir)
        os.remove(tmpfile)
    _upload_template('nginx.conf', env.nginx_conf, context=context, user=env.deploy_user,
                     use_jinja=True, template_dir=env.templates_dir)
    _upload_template('web-rc.local', '/etc/rc.local', context=context,
                     user='root', use_jinja=True, template_dir=env.templates_dir)
    sudo('chmod a+x /etc/rc.local')
    with settings(warn_only=True):
        sudo('rm -f /etc/nginx/sites-enabled/default')
        sudo('rm -f /etc/nginx/sites-enabled/%(project)s-*.conf' % env)
    sudo('ln -s %(nginx_conf)s /etc/nginx/sites-enabled/%(project)s-%(environment)s.conf' % env)
    uncomment('/etc/nginx/nginx.conf', 'server_names_hash_bucket_size', use_sudo=True)
    sed('/etc/nginx/nginx.conf', 'server_names_hash_bucket_size .+', 'server_names_hash_bucket_size 128;', use_sudo=True)
    restart_nginx()


@task
@parallel
@roles('web', 'worker')
def upload_newrelic_conf():
    """Upload New Relic configuration from the template."""

    require('environment', provided_by=env.environments)
    _load_passwords(env.password_names)
    template = os.path.join(env.templates_dir, 'newrelic.ini')
    context = dict(env)
    # need different app names for New Relic web interface so Celery and Gunicorn can be distinguished
    context['app_type'] = 'web'
    destination = os.path.join(env.services, 'newrelic-%(environment)s-%(app_type)s.ini' % context)
    _upload_template(template, destination, context=context, user=env.deploy_user)
    context['app_type'] = 'celery'
    destination = os.path.join(env.services, 'newrelic-%(environment)s-%(app_type)s.ini' % context)
    _upload_template(template, destination, context=context, user=env.deploy_user)


@task
@parallel
@roles('web', 'worker')
def update_services():
    """ upload changes to services configurations as nginx """

    setup_dirs()
    upload_newrelic_conf()
    upload_supervisor_conf()
    upload_pgbouncer_conf()
    if 'web' in _current_roles():
        upload_nginx_conf()


@task
@parallel
@roles('web', 'worker')
def create_virtualenv():
    """ setup virtualenv on remote host """

    require('virtualenv_root', provided_by=env.environments)
    cmd = ['virtualenv', '--clear', '--distribute',
           '--python=%(python)s' % env, env.virtualenv_root]
    sudo(' '.join(cmd), user=env.deploy_user)


@task
@parallel
@roles('web', 'worker')
def update_requirements():
    """ update external dependencies on remote host """

    require('code_root', provided_by=env.environments)
    # add HOME= so if there's an error, pip can save the log (Fabric doesn't
    # pass -H to sudo)
    cmd = ['HOME=%(home)s %(virtualenv_root)s/bin/pip install -q' % env]
    if env.requirements_sdists:
        sdists = os.path.join(env.code_root, env.requirements_sdists)
        cmd += [' --no-index --find-links=file://%s' % sdists]
    apps = os.path.join(env.code_root, env.requirements_file)
    cmd += ['--requirement %s' % apps]
    sudo(' '.join(cmd), user=env.deploy_user)


@task
@parallel
@roles('web', 'worker')
def update_local_settings():
    """ create local_settings.py on the remote host """

    require('environment', provided_by=env.environments)
    _load_passwords(env.password_names)
    assert env.master_database, 'Primary database missing'
    assert env.cache_server, 'Cache server missing'
    # must update pgbouncer configuration at the same time to ensure ports stay
    # in sync
    upload_pgbouncer_conf()
    if not env.slave_databases:
        print 'WARNING: No replica DBs found; using primary DB as read DB'
        env.slave_databases.append(env.master_database)
    context = env.copy()
    context['current_changeset'] = current_changeset()
    context['current_role'] = _current_roles()[0]
    context['allowed_hosts'] = _allowed_hosts()
    _upload_template(os.path.basename(env.localsettings_template),
                     env.local_settings_py, context=context,
                     user=env.deploy_user, use_jinja=True,
                     template_dir=os.path.dirname(env.localsettings_template))


@task
@parallel
@roles('web', 'worker')
def bootstrap(purge=False):
    """ initialize remote host environment (virtualenv, deploy, update) """

    require('environment', provided_by=env.environments)

    if purge:
        sudo('rm -rf %(root)s' % env)
    sudo('mkdir -p %(root)s' % env, user=env.deploy_user)
    clone_repo()
    update_services()
    create_virtualenv()
    update_requirements()


###### CODE DEPLOYMENT ######


@task
@roles('web', 'worker')
def update_source(changeset=None):
    """Checkout the latest code from repo."""
    require('environment', provided_by=env.environments)
    with cd(env.code_root):
        sudo('find . -name "*.pyc" -delete')
        if env.vcs_cmd.endswith('git'):
            vcs('fetch')
            # Assumption: if changeset is provided, it's a commit hash, not a branch name
            if changeset is None:
                changeset = env.branch
                if not changeset.startswith('origin/'):
                    changeset = 'origin/%s' % changeset
            vcs('reset', ['--hard', changeset])
        else:
            if changeset is None:
                changeset = env.branch
            vcs('pull')
            vcs('update', [changeset])


@task
@roles('web', 'worker')
def current_changeset():
    """Checkout the latest code from repo."""

    require('environment', provided_by=env.environments)
    with cd(env.code_root):
        return sudo(env.latest_changeset_cmd, user=env.deploy_user).strip()


def _call_managepy(cmd, pty=False):
    """Calls the given management command."""
    env.managepy_cmd = cmd
    if env.settings_managepy:
        env.managepy_cmd += ' --settings=%s' % env.settings_managepy
    with cd(env.code_root):
        # cd to project_root to ensure local_settings is on the path
        sudo('%(virtualenv_root)s/bin/python '
             'manage.py %(managepy_cmd)s' % env,
             user=env.webserver_user, pty=pty)


@task
@roles('worker')
def managepy(cmd):
    """Runs the given management command."""

    require('environment', provided_by=env.environments)
    _call_managepy(cmd)


@task
@roles('worker')
@runs_once
def migrate():
    """Run Django migrations."""

    require('environment', provided_by=env.environments)
    cmd = 'migrate --noinput'
    _call_managepy(cmd)


@task
@roles('worker', 'web')
def collectstatic():
    """Collect static files."""

    require('environment', provided_by=env.environments)
    _call_managepy('collectstatic --noinput')


@task
@roles('worker')
@runs_once
def dbbackup():
    """Run a database backup."""

    require('environment', provided_by=env.environments)
    _call_managepy('dbbackup')


@task
@roles('worker')
@runs_once
def dbrestore(filepath):
    """Run a database backup. Before running this you must have the GPG key in your GPG key ring."""

    require('environment', provided_by=env.environments)
    answer = prompt('Are you sure you want to DELETE and REPLACE the {0} '
                    'database with a copy of {1}?\n**THIS WILL COMPLETELY ERASE '
                    'THE CURRENT DATABASE AND REPLACE IT WITH THE COPY OF THIS '
                    'BACKUP.**'.format(env.environment.upper(), filepath), default='n')
    if answer != 'y':
        abort('Aborted.')
    # make sure we have the key before taking down the servers
    dest = '/tmp'
    private_key = os.path.join(dest, 'caktus_admin-private.asc')
    local('gpg --export-secret-keys --armor Caktus > {0}'.format(os.path.join(dest,'caktus_admin-private.asc')))
    try:
        executel('begin_upgrade')
        executel('supervisor', 'stop', 'web', roles=['web'])
        executel('supervisor', 'stop', 'celery', roles=['worker'])
        executel('supervisor', 'stop', 'pgbouncer')
        with env.master_database:
            sudo('dropdb {0}'.format(env.database_name), user='postgres')
        env.servers['db-primary'][0].create_db(env.database_name, owner=env.database_user)
        executel('supervisor', 'start', 'pgbouncer')
        with cd(dest):
            put(private_key, dest)
            with settings(warn_only=True):
                sudo('gpg --homedir {0} --batch --delete-secret-keys "{1}"'.format(env.gpg_dir, env.backup_key_fingerprint), user=env.webserver_user)
            sudo('gpg --homedir {0} --import {1}'.format(env.gpg_dir, os.path.split(private_key)[1]), user=env.webserver_user)
            _call_managepy('dbrestore --database=default --input-filename={0}'.format(filepath), pty=True)
            sudo('gpg --homedir {0} --batch --delete-secret-keys "{1}"'.format(env.gpg_dir, env.backup_key_fingerprint), user=env.webserver_user)
            sudo('gpg --homedir {0} -K'.format(env.gpg_dir), user=env.webserver_user)
            sudo('rm {0}'.format(os.path.join(dest, os.path.split(private_key)[1])))
        executel('migrate')
        executel('supervisor', 'start', 'celery', roles=['worker'])
        executel('supervisor', 'start', 'web', roles=['web'])
        executel('end_upgrade')
    finally:
        local('rm {0}'.format(private_key))


@task
@parallel
@roles('web')
def restart_nginx():
    """Restart Nginx."""

    require('environment', provided_by=env.environments)
    system.restart_service('nginx')


@task
@parallel
@roles('web', 'worker')
def supervisor(command, group, process=None):
    """Restart Supervisor controlled process(es).  If no process is specified, all the given command is run on all processes."""

    require('environment', provided_by=env.environments)
    env.supervisor_command = command
    env.supervisor_group = group
    if process:
        env.supervisor_process = process
        supervisor_command('%(supervisor_command)s %(environment)s-%(supervisor_group)s:%(environment)s-%(supervisor_process)s' % env)
    else:
        supervisor_command('%(supervisor_command)s %(environment)s-%(supervisor_group)s:*' % env)


@task
@roles('web')
@parallel
def begin_upgrade(stay_healthy=True):
    """Enable an 503 Service Unavailable upgrade message via Nginx"""

    require('environment', provided_by=env.environments)
    files = [env.static_html['upgrade_message']]
    if stay_healthy:
        files.append(env.static_html['healthcheck_override'])
    for file_ in files:
        put(file_, '{0}/nginx/html'.format(env.services), use_sudo=True)


@task
@roles('web')
@parallel
def end_upgrade():
    """Disable the 503 Service Unavailable upgrade message via Nginx"""

    require('environment', provided_by=env.environments)
    for file_ in env.static_html.values():
        with settings(warn_only=True):
            sudo('rm {0}/nginx/html/{1}'.format(env.services, os.path.basename(file_)))


@task
@roles('worker')
def flag_deployment():
    """Using the new relic API, flag this deployment in the timeline"""
    _load_passwords(['newrelic_api_key'])
    context = dict(env)
    context['changeset'] = current_changeset()
    context['local_user'] = local('whoami', capture=True)
    # web application
    local('curl -H "x-api-key:%(newrelic_api_key)s" '
          '-d "deployment[app_name]=%(deployment_tag)s %(environment)s (web)" '
          '-d "deployment[revision]=%(changeset)s" '
          '-d "deployment[user]=%(local_user)s" '
          'https://api.newrelic.com/deployments.xml' % context)
    # celery application
    local('curl -H "x-api-key:%(newrelic_api_key)s" '
          '-d "deployment[app_name]=%(deployment_tag)s %(environment)s (celery)" '
          '-d "deployment[revision]=%(changeset)s" '
          '-d "deployment[user]=%(local_user)s" '
          'https://api.newrelic.com/deployments.xml' % context)


@task
@parallel
@roles('web')
def deploy_web(changeset=None):
    """Deploy to a given environment."""

    require('environment', provided_by=env.environments)
    supervisor('stop', 'web')
    supervisor('stop', 'pgbouncer')
    update_source(changeset=changeset)
    update_requirements()
    update_local_settings()
    upload_supervisor_conf()
    if getattr(env, 'static_hosting', 'remote') == 'local':
        collectstatic()
        with settings(warn_only=True):
            _call_managepy('compress')
    supervisor('start', 'pgbouncer')
    supervisor('start', 'web')


@task
@roles('worker')
@runs_once
def deploy_worker(changeset=None):
    """
    Update the code on the celery worker, sync the database, and collect static media on S3.
    """

    require('environment', provided_by=env.environments)
    supervisor('stop', 'celery')
    supervisor('stop', 'pgbouncer')
    update_source(changeset=changeset)
    update_requirements()
    update_local_settings()
    upload_supervisor_conf()
    supervisor('start', 'pgbouncer')
    migrate()
    collectstatic()
    with settings(warn_only=True):
        _call_managepy('compress')
    supervisor('start', 'celery')
    flag_deployment()


@task
@roles('web')
@runs_once
def add_to_elb():
    """Prepares and adds a new instance to the load balancer(s) for the current environment."""

    require('environment', provided_by=env.environments)
    servers = env.servers['web']
    initial_states = dict([(server.instance.id, server.elb_state(elb_name))
                           for server in servers for elb_name in env.elb_names])
    assert 'InService' not in initial_states.values(), 'Instance(s) already in load balancer(s)'
    for server in servers:
        with server:
            begin_upgrade(stay_healthy=False)
            deploy_web()
            end_upgrade()
        for elb_name in env.elb_names:
            print 'Adding instance %s to ELB %s' % (server.instance.id, elb_name)
            server.add_to_elb(elb_name)
            state = server.wait_for_elb_state(elb_name, 'InService')
            print 'Instance %s now in state %s' % (server.instance.id, state)


@task
@roles('web')
@runs_once
def add_all_to_elb():
    """Adds all web servers for the given environment to the appropriate load balancer(s)."""

    require('environment', provided_by=env.environments)
    servers = env.servers['web']

    for elb_name in env.elb_names:
        for server in servers:
            server.add_to_elb(elb_name)
        for server in servers:
            state = server.wait_for_elb_state(elb_name, 'InService')
            print 'Instance %s now in state %s' % (server.instance.id, state)


###### DATABASE MAINTENANCE ######


@task
@roles('db-primary') # only supported on combo web & database servers
def reload_production_db(prod_env=env.default_deployment, src_env='production'):
    """ Replace the testing or staging database with the production database """
    if env.environment not in ('staging', 'testing'):
        abort('prod_to_staging requires the staging or testing environment.')
    executel('suspend_autoscaling_processes', env.deployment_tag, env.environment)
    executel('begin_upgrade')
    executel('supervisor', 'stop', 'web', roles=['web'])
    executel('supervisor', 'stop', 'celery', roles=['worker'])
    executel('supervisor', 'stop', 'pgbouncer')
    with settings(warn_only=True):
        sudo('dropdb {0}'.format(env.database_name), user='postgres')
    env.servers['db-primary'][0].create_db(env.database_name, owner=env.database_user)
    prod_servers = _get_servers(prod_env, src_env, 'db-primary')
    prod_hosts = [server.hostname for server in prod_servers]
    dump_cmd = 'ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 '\
               '-C {user}@{host} pg_dump -Ox {db_name}'.format(
        user=env.deploy_user,
        host=prod_hosts[0],
        db_name=env.database_name.replace(env.environment, src_env),
    )
    load_cmd = 'bash -o pipefail -c "{dump_cmd} | psql {db_name}"'.format(
        dump_cmd=dump_cmd,
        db_name=env.database_name,
    )
    sshagent_run(load_cmd, user=env.deploy_user)
    executel('supervisor', 'start', 'pgbouncer')
    executel('migrate')
    executel('supervisor', 'start', 'celery', roles=['worker'])
    executel('supervisor', 'start', 'web', roles=['web'])
    executel('end_upgrade')
    executel('resume_autoscaling_processes', env.deployment_tag, env.environment)


@task
@roles('db-primary')
def reset_local_db(db_name):
    """ Replace the local database with the remote database """

    require('environment', provided_by=env.environments)
    answer = prompt('Are you sure you want to reset the local database {0} '
                    'with a copy of the {1} database?\n**YOUR DATABASE MUST BE '
                    'RUNNING ON AN ENCRYPTED FILESYSTEM TO USE THIS FEATURE.**'
                    ''.format(db_name, env.environment), default='n')
    if answer != 'y':
        abort('Aborted.')
    with settings(warn_only=True):
        local('dropdb {0}'.format(db_name))
    local('createdb {0}'.format(db_name))
    cmd = 'ssh -C {user}@{host} pg_dump -Ox {db_name} | '.format(
        user=env.deploy_user,
        host=env.host_string,
        db_name=env.database_name,
    )
    cmd += 'psql {0}'.format(db_name)
    local(cmd)


@task
@roles('db-replica')
def reset_slaves():
    """Manually copy the current primary database to the slaves."""

    require('environment', provided_by=env.environments)
    _load_passwords(['database_password'])
    primary = env.servers['db-primary'][0]
    _current_server().pg_copy_master(primary, '%s_repl' % env.database_user, env.database_password)


@task
@runs_once
@roles('db-replica')
def promote_replica(index=0, override_servers={}):
    """Promotes a replica to the db-primary role and decommissions the old primary."""

    require('environment', provided_by=env.environments)
    replica = env.servers['db-replica'][int(index)]
    replica.pg_promote()
    for server in env.servers['db-primary']:
        _change_role(server, 'db-primary-OLD')
        with server:
            with settings(warn_only=True):
                # Shoot The Other Node In The Head:
                sudo('service postgresql stop')
    _change_role(replica, 'db-primary')
    _setup_env(override_servers=override_servers)
    if env.gelf_log_host:
        executel('install_logstash', roles=['db-primary'])
    if env.syslog_server:
        executel('install_rsyslog', roles=['db-primary'])
    if env.awslogs_access_key_id:
        executel('install_awslogs', roles=['db-primary'])
    print 'NOTE: you must now update the local_settings.py files on the web'\
          'servers to point to the new primary DB ({0}).'.format(replica.hostname)


###### ROUTINE MAINTENANCE ######


@task
@runs_once
def update_sysadmin_users():
    """Create sysadmin users on the server"""

    require('environment', provided_by=env.environments)
    for role, servers in env.servers.iteritems():
        for server in servers:
            server.create_users(server._get_users())
            server.update_deployer_keys()


@task
def upgrade_packages():
    """ update packages on the servers """

    with settings(warn_only=True):
        sudo('apt-get -qq update || apt-get -qq update')
    if 'web' in _current_roles() or 'worker' in _current_roles():
        packages = env.app_server_packages
        sudo('apt-get -qq -y install {0}'.format(' '.join(packages)))
    sudo('apt-get -qq -y upgrade')


@task
@parallel
def update_server_passwords():
    """Pushes password values from local fabsecrets.py file up to the servers"""

    require('environment', provided_by=env.environments)
    _load_passwords(env.password_names)
    with cd(env.home):
        for passname in env.password_names:
            passwd = getattr(env, passname)
            sudo('echo "{0}" > {1}'.format(passwd, passname), user=env.deploy_user)
            sudo('chmod 600 {0}'.format(passname), user=env.deploy_user)


@task
@parallel
def mount_encrypted(drive_letter='f'):
    """mount the luks encrypted partition and start the services there"""
    require('environment', provided_by=env.environments)
    if not env.host_string:
        print 'no hosts found; exiting cleanly'
        return
    device = '/dev/sd' + drive_letter
    crypt = 'crypt-sd' + drive_letter
    if not exists(device):
        device = '/dev/xvd' + drive_letter
        crypt = 'crypt-xvd' + drive_letter
    crypt_dev = '/dev/mapper/{0}'.format(crypt)
    if exists(crypt_dev):
        print '{0} already exists on {1}, exiting'.format(crypt_dev, env.host_string)
        return
    _load_passwords(['luks_passphrase'])
    # stop redis and nginx (postgres will have failed to start without
    # /var/lib/postgres, so no need to stop it):
    if 'cache' in _current_roles():
        sudo('service redis-server stop', pty=False)
    if 'web' in _current_roles():
        sudo('service nginx stop')
    answers = [('Enter passphrase for .+:', env.luks_passphrase)]
    answer_sudo('cryptsetup luksOpen {device} {crypt}'
                ''.format(device=device, crypt=crypt),
                answers=answers)
    current_server = _current_server()
    if exists(current_server.mount_script):
        sudo(current_server.mount_script)
    else:
        abort('attempting to mount encrypted partitions, but mount script {} '
              'does not exist'.format(current_server.mount_script))
    if exists(current_server.default_swap_file):
        sudo('swapon %s' % current_server.default_swap_file)
    if 'db-primary' in _current_roles() or 'db-replica' in _current_roles():
        sudo('service postgresql start')
    if 'cache' in _current_roles():
        sudo('service redis-server start', pty=False)
        sudo('service rabbitmq-server start', pty=False)
        print '*** WARNING: While immediately restarting a cache server works as expected, '\
              'stopping and later restarting does not. For more information, see docs/servers/maintenance.rst ***'
    if 'web' in _current_roles():
        # if we're being created from an image, make sure the hostname gets updated
        # in both the Nginx config and local_settings.py
        upload_nginx_conf()
        update_local_settings()
        # make sure our worker count is updated to reflect our CPU core count
        upload_supervisor_conf(run_update=False)
        # supervisor may have failed to start during initial boot
        # note: this will auto-start services marked as such in the supervisor config
        sudo('service supervisor restart')
        # start everything back up, if not already started by 'supervisor restart'
        supervisor('start', 'pgbouncer')
        supervisor('start', 'web')
        sudo('service nginx start')
    if 'worker' in _current_roles():
        # if we're being created from an image, make sure the hostname gets updated
        update_local_settings()
        # make sure our worker count is updated to reflect our CPU core count
        upload_supervisor_conf(run_update=False)
        # supervisor may have failed to start during initial boot
        sudo('service supervisor restart')
        # start everything back up
        supervisor('start', 'pgbouncer')
        supervisor('start', 'celery')
    # make sure logging services are running and notice any now-present log
    # files after the encrypted partition has been mounted
    if env.gelf_log_host:
        sudo('service logstash-agent restart')
    if env.syslog_server:
        sudo('service rsyslog restart')
    if env.awslogs_access_key_id:
        sudo('service awslogs restart')


###### TESTING and USAGE EXAMPLES ######


def executel(cmd, *args, **kwargs):
    """Wrapper for execute() that enables visible logging of commands being run"""
    if hasattr(cmd, 'name'):
        name = cmd.name.upper()
    else:
        name = str(cmd).upper()
    arguments = [str(v) for v in args] + ['%s=%s' % (k, v) for k, v in kwargs.iteritems()]
    logger.info('\n\n **** %s (%s) ****\n\n' % (name, ', '.join(arguments)))
    execute(cmd, *args, **kwargs)


@task
@runs_once
def create_environment(deployment_tag, environment, num_web=2):
    """Sets up all servers for the given environment for the first time."""

    _setup_env(deployment_tag, environment)
    print 'Starting AMI and launch config creation in the background'
    # make sure we don't pass open SSH connections down to the child procs
    disconnect_all()
    lc_creator = BackgroundCommand(_create_server_for_image, capture_result=True)
    lc_creator.start()
    az_1 = env.avail_zones[0]
    az_2 = env.avail_zones[1]
    servers = [
        (deployment_tag, environment, 'db-primary', az_1),
        (deployment_tag, environment, 'db-replica', az_2),
        (deployment_tag, environment, 'cache', az_2),
        (deployment_tag, environment, 'worker', az_1),
    ]
    _create_many(servers)
    env.roles = []
    executel(environment, deployment_tag)
    # if we create all servers at once, the replica won't be sync'ed yet
    executel('reset_slaves')

    print 'Waiting for launch config creation to complete...'
    # wait for the launch config to finish creating if needed
    lc_creator.join()
    instance_id = lc_creator.result()
    # reload the environment once more, after we know the background image
    # creation is finished
    _setup_env(deployment_tag, environment)
    server = _get_servers(deployment_tag, environment, 'web',
                          instance_ids=[instance_id])[0]
    # shutdown the server and create the AMI & Launch config
    lc = _create_launch_config(server=server)
    # clean up the leftover server in EC2
    server.terminate()
    print 'Running deploy_full...'
    # run the initial deployment with the new AMI containing the latest code
    deploy_full(deployment_tag, environment, launch_config_name=lc.name, num_web=num_web)

    print 'The non-web servers have been created and the autoscaling group has been updated '\
          'with a new launch configuration.'


@task
@runs_once
def update_environment(deployment_tag, environment):
    """Runs period maintenance tasks on the servers to ensure they're up to date."""
    executel(environment, deployment_tag)
    executel('update_sysadmin_users')
    executel('update_server_passwords')
    executel('upgrade_packages')


@task
@runs_once
def reboot_environment(deployment_tag, environment, sleep_time=180):
    """Tests rebooting and re-mounting the encrypted drives on all servers."""
    sleep_time = int(sleep_time)
    executel(environment, deployment_tag)
    for role, servers in env.servers.iteritems():
        if role == 'logger':
            continue
        for server in servers:
            logger.info('Rebooting %s server %s (%s)' % (role, server.hostname,
                                                         server.instance.id))
            server.reboot()
    logger.info('Sleeping for %s seconds' % sleep_time)
    time.sleep(sleep_time)
    executel('mount_encrypted', roles=['db-primary', 'cache'])
    executel('mount_encrypted', roles=['db-replica'])
    executel('mount_encrypted', roles=['web', 'worker'])


@task
@runs_once
def update_newrelic_keys(deployment_tag, environment):
    executel(environment, deployment_tag)
    answer = prompt('Are you sure you want to update the New Relic license and '
                    'API keys on the %s environment? This will require a brief '
                    'moment of downtime while Gunicorn is restarted.'
                    '' % env.environment.upper(), default='n')
    if answer != 'y':
        abort('Aborted.')
    executel('upload_newrelic_conf')
    executel('supervisor', 'restart', 'celery', roles=['worker'])
    executel('begin_upgrade')
    executel('supervisor', 'restart', 'web', roles=['web'])
    executel('end_upgrade')


@task
@runs_once
def describe(deployment_tag, environment):
    executel(environment, deployment_tag)
    roles = env.roles
    roles.sort()
    for role in roles:
        if env.servers[role]:
            print '{0} servers:'.format(role)
            for server in env.servers[role]:
                print '  Instance ID: {0}'.format(server.instance.id)
                print '     Hostname: {0}'.format(server.hostname)
                print '  Internal IP: {0}'.format(server.internal_ip)
                print '    Placement: {0}'.format(server._placement)
                if role == 'web':
                    elb_names = _find(env.load_balancers, env.deployment_tag, env.environment)
                    for elb_name in elb_names:
                        print '    ELB State: {0} ({1})'.format(server.elb_state(elb_name), elb_name)
                print ''
            print ''


@task
@runs_once
def deploy_full_without_autoscaling(deployment_tag, environment):
    """Runs a full deploy in parallel on the given deployment and environment."""
    _check_local_deps()
    executel(environment, deployment_tag)
    executel('begin_upgrade')
    executel('deploy_worker')
    executel('deploy_web')
    executel('end_upgrade')


@task
@runs_once
def deploy_serial_without_autoscaling(deployment_tag, environment, wait=30):
    """Safely deploy to a given environment with no downtime."""

    _check_local_deps()
    executel(environment, deployment_tag)
    wait = float(wait)
    servers = env.servers['web']
    initial_states = dict([((server.instance.id, elb_name), server.elb_state(elb_name))
                           for server in servers for elb_name in env.elb_names])
    # make sure we have at least two servers in service in the load balancer(s)
    assert initial_states.values().count('InService') >= 2*len(env.elb_names), \
           'Need 2 or more instances per load balancer in service to run deploy_serial_without_autoscaling'
    executel('deploy_worker')
    for server in servers:
        for elb_name in env.elb_names:
            if initial_states[(server.instance.id, elb_name)] == 'InService':
                print 'Removing instance %s from ELB %s' % (server.instance.id, elb_name)
                server.remove_from_elb(elb_name)
            state = server.wait_for_elb_state(elb_name, 'OutOfService')
            print 'Instance %s now in state %s' % (server.instance.id, state)
        print 'Waiting %s seconds for requests to finish processing...' % wait
        time.sleep(wait) # wait for instance to process outstanding requests
        # be honest to the load balancer(s) about our status (not healthy)
        executel('begin_upgrade', stay_healthy=False, hosts=[server.hostname])
        executel('deploy_web', hosts=[server.hostname])
        executel('end_upgrade', hosts=[server.hostname])
        for elb_name in env.elb_names:
            if initial_states[(server.instance.id, elb_name)] == 'InService':
                print 'Adding instance %s to ELB %s' % (server.instance.id, elb_name)
                server.add_to_elb(elb_name)


@task
@runs_once
def recreate_servers(deployment_tag, environment, wait=30):
    """Recreate all the servers in a given environment, and decommission the old ones."""

    _setup_env(deployment_tag, environment)
    config = {}
    orig_servers = dict(env.servers.items())
    for role, servers in orig_servers.iteritems():
        config[role] = [s._placement[-1] for s in servers]
    print 'Starting AMI and launch config creation in the background'
    # make sure we don't pass open SSH connections down to the child procs
    disconnect_all()
    lc_creator = BackgroundCommand(_create_server_for_image, capture_result=True)
    lc_creator.start()
    print 'Recreating servers for: %s' % config
    # first, create a new replica & cache to replace the current primary & cache servers
    servers = [(deployment_tag, environment, 'db-replica', config['db-primary'][0])]
    servers += [(deployment_tag, environment, 'cache', z) for z in config['cache']]
    _create_many(servers)
    start_time = datetime.datetime.now()
    executel('begin_upgrade')
    _stop_all()
    print 'Decommisioning old servers...'
    # rename the original replica server(s)
    for replica in orig_servers['db-replica']:
        _change_role(replica, 'db-replica-OLD')
    for cache in orig_servers['cache']:
        _change_role(cache, 'cache-OLD')
    # reload the environment with the new replica (soon to be primary),
    # but ensure the web server being created in the background is
    # not added
    override = {'web': orig_servers['web']}
    _setup_env(deployment_tag, environment, override_servers=override)
    # promote that replica to the primary role
    executel('promote_replica', override_servers=override)
    # update local_settings.py with new, single primary
    executel('update_local_settings')
    _start_all()
    executel('end_upgrade')
    end_time = datetime.datetime.now()
    downtime = end_time - start_time
    print 'downtime complete; total = %s secs' % downtime.total_seconds()

    # next, create the new replica, worker, and web servers
    servers = [(deployment_tag, environment, 'db-replica', z) for z in config['db-replica']]
    servers += [(deployment_tag, environment, 'worker', config['worker'][0])]
    _create_many(servers)
    for worker in orig_servers['worker']:
        executel('supervisor', 'stop', 'celery', hosts=[worker.hostname])
        _change_role(worker, 'worker-OLD')

    # wait for the launch config to finish creating if needed
    print 'waiting for launch config to finish creating'
    lc_creator.join()
    instance_id = lc_creator.result()
    # reload the environment once more, after we know the background image
    # creation is finished
    _setup_env(deployment_tag, environment)
    server = _get_servers(deployment_tag, environment, 'web',
                          instance_ids=[instance_id])[0]
    # shutdown the server and create the AMI & Launch config
    lc = _create_launch_config(server=server)
    # clean up the leftover server in EC2
    server.terminate()
    # make sure all the web servers get re-created using auto-scaling
    deploy_serial(deployment_tag, environment, launch_config_name=lc.name, answer='y')

    print 'recreate_servers complete; total downtime was %s secs' % downtime.total_seconds()


@task
@parallel
def install_munin():
    require('environment', provided_by=env.environments)
    sudo('apt-get -qq -y install munin-node munin-plugins-extra libdbd-pg-perl')
    append('/etc/munin/munin-node.conf', 'allow_cidr 10.0.0.0/8', use_sudo=True)
    append('/etc/munin/munin-node.conf', 'allow_cidr 172.16.0.0/12', use_sudo=True)
    append('/etc/munin/munin-node.conf', 'allow_cidr 192.168.0.0/16', use_sudo=True)
    sudo('service munin-node restart')


@task
@parallel
def install_rsyslog():
    require('environment', provided_by=env.environments)
    context = dict(env)
    context['current_role'] = _current_roles()[0]
    destination = os.path.join('/etc', 'rsyslog.d/%(project)s-%(environment)s.conf' % env)
    _upload_template('rsyslog.conf', destination, user='root', context=context,
                     use_jinja=True, template_dir=env.templates_dir)

    output = run('rsyslogd -v')
    if 'rsyslogd 8' not in output:
        sudo("add-apt-repository --yes ppa:adiscon/v8-stable")
        with settings(warn_only=True):
            sudo("apt-get -qq update || apt-get -qq update")
        sudo("apt-get -qq -y install rsyslog")

    print 'Ignore any useradd or chgrp warnings below.'
    with settings(warn_only=True):
        sudo('useradd --system --groups adm syslog')
    sudo('service rsyslog restart')


@task
@parallel
def install_logstash():
    """
    Install logstash agent. Requires an Upstart-based OS (e.g., Ubuntu 14.04).
    """
    require('environment', provided_by=env.environments)
    context = dict(env)
    context['current_role'] = _current_roles()[0]
    destination = os.path.join('/etc', 'logstash-%(environment)s.conf' % env)
    _upload_template('logstash.conf', destination, user='root', context=context,
                     use_jinja=True, template_dir=env.templates_dir)
    template = os.path.join(env.templates_dir, 'logstash-agent.conf')
    destination = '/etc/init/logstash-agent.conf'
    _upload_template(template, destination, user='root', context=context)
    with(cd('/tmp')):
        if not exists('logstash.jar'):
            sudo('apt-get -qq -y install default-jre')
            sudo('wget https://download.elasticsearch.org/logstash/logstash/logstash-1.1.7-monolithic.jar -O logstash.jar', user=env.deploy_user)
            print 'Ignore any useradd or chgrp warnings below.'
            with settings(warn_only=True):
                sudo('useradd --system --groups adm logstash')
                sudo('chgrp -R adm /var/log/rabbitmq')
                sudo('chgrp -R adm /var/log/redis')
                #sudo('adduser logstash redis')
                #sudo('adduser logstash rabbitmq')
    sudo('service logstash-agent restart')


@task
@parallel
def install_awslogs():
    """
    Install awslogs agent. Requires a systemd-based OS (e.g., Ubuntu 16.04+).
    """
    require('environment', provided_by=env.environments)
    _load_passwords(['awslogs_secret_access_key'])
    context = dict(env)
    context['current_role'] = _current_roles()[0]
    # upload the config for the AWS CloudWatch Logs agent itself
    destination = '/tmp/awslogs.conf'
    _upload_template('awslogs/awslogs.conf', destination, user='root', context=context,
                     use_jinja=True, template_dir=env.templates_dir)
    # add our custom systemd init script
    template = os.path.join(env.templates_dir, 'awslogs', 'awslogs.service')
    destination = '/etc/init/awslogs.service'
    _upload_template(template, destination, user='root', context=context)
    with(cd('/tmp')):
        sudo('curl https://s3.amazonaws.com/aws-cloudwatch/downloads/latest/awslogs-agent-setup.py -O', user=env.deploy_user)
        sudo('python awslogs-agent-setup.py --region us-east-1 --non-interactive --configfile awslogs.conf')
        sudo('rm awslogs.conf')
    # upload AWS credentials
    template = os.path.join(env.templates_dir, 'awslogs', 'aws.conf')
    destination = '/var/awslogs/etc/aws.conf'
    _upload_template(template, destination, user='root', context=context)
    # enable & start the service
    sudo('systemctl enable awslogs.service')
    sudo('systemctl start awslogs.service')
    sudo('service awslogs restart')


@task
def generate_and_upload_munin_conf(deployment_tag, environment):
    """Generate and upload the munin server configuration based on servers in the current environment."""
    executel(environment, deployment_tag)
    roles = env.roles
    roles.sort()
    munin_conf = ''
    for role in roles:
        if env.servers[role]:
            munin_conf += '\n# {0} servers:\n'.format(role)
            for server in env.servers[role]:
                munin_conf += """[%s_%s;%s;%s]
    address %s
    use_node_name yes
""" % (deployment_tag, environment, role, server.hostname, server.internal_ip)
    executel('upload_munin_conf', deployment_tag, environment, munin_conf)


### Autoscaling ###


@task
@runs_once
def suspend_autoscaling_processes(deployment_tag, environment, *processes):
    executel(environment, deployment_tag)
    group = _get_autoscaling_group()
    group.suspend_processes(processes or None)
    processes = ', '.join(processes) if processes else "all processes"
    print ("Suspended these processes for the autoscaling group named "
           "'{0}': {1}".format(group.name, processes))


@task
@runs_once
def resume_autoscaling_processes(deployment_tag, environment, *processes):
    executel(environment, deployment_tag)
    group = _get_autoscaling_group()
    group.resume_processes(processes or None)
    processes = ', '.join(processes) if processes else "all processes"
    print ("Resumed these processes for the autoscaling group named "
           "'{0}': {1}".format(group.name, processes))


@task
@runs_once
def create_launch_config_for_deployment(deployment_tag, environment):
    """Create a launch configuration for the deployment code.

    Since image creation is the most time-consuming part of the deploy,
    this command can be used to create it and an associated launch
    configuration ahead of time. The deploy itself, using the new launch
    configuration, can be done as a separate step.
    """
    executel(environment, deployment_tag)
    launch_config = _create_launch_config()
    print ("Created a new launch configuration named '{0}' to deploy "
           "{1}.".format(launch_config.name, launch_config.image_id))


@task
def deploy_full(deployment_tag, environment, launch_config_name=None, num_web=2):
    """Autoscaling replacement for deploy_full_without_autoscaling.

    Performs a full deployment of new code. Users who visit the site during
    the critical parts of the upgrade will be shown a 503 error message.
    """
    _check_local_deps()
    executel(environment, deployment_tag)

    if _is_production(env.environment):
        answer = prompt("Are you sure you want to run a deploy_full in production? "
                        "This will cause downtime! (y/N)? ",
                        default='n')
        if not answer.lower().startswith('y'):
            abort("Not running deploy_full on production")

    if not launch_config_name:
        launch_config = _create_launch_config()
    else:
        launch_config = _get_launch_config(launch_config_name)
    group = _get_autoscaling_group()

    # Prevent the group from creating new instances before we're ready.
    group.suspend_processes(["Launch"])
    print "Suspended 'Launch' autoscaling process."

    # Update the group to use the new launch config.
    group = _update_autoscaling_group(launch_config)

    # Temporarily adjust the group settings so that it will be forced to
    # create the desired number of new instances using the updated launch
    # configuration.
    # if desired is "0", use a sane default (e.g., if we were called by
    # create_environment)
    curr_minimum = group.min_size or num_web
    curr_desired = group.desired_capacity or num_web
    curr_servers = len(group.instances)
    group.min_size = group.desired_capacity = curr_servers + curr_desired
    group.desired_capacity = group.min_size
    # ensure max_size is at least as big as min_size
    group.max_size = max(group.max_size, group.min_size)
    group.update()
    print ("Temporarily updated the autoscaling group's minimum/desired "
           "instance capacity to {0}".format(curr_servers + curr_desired))

    # Allow the group to create the new instances, but not to add them
    # to the load balancer(s) just yet.
    group.suspend_processes(["AddToLoadBalancer"])
    print "Suspended 'AddToLoadBalancer' autoscaling process."
    group.resume_processes(["Launch"])
    print "Resumed 'Launch' autoscaling process."

    # Wait for new instances to be created.
    print "Waiting for new instances to be in service."
    waited = 0
    while True:
        time.sleep(5)
        waited += 5
        group = _get_autoscaling_group()  # Refresh instances.
        new_instances = [i for i in group.instances
                         if i.launch_config_name == group.launch_config_name
                            and i.lifecycle_state == "InService"]
        if len(new_instances) >= curr_minimum:
            print ("Created {0} new servers in {1} "
                   "seconds.".format(len(new_instances), waited))
            break
        else:
            count = len(new_instances)
            print ("{0} seconds: Have {1} instances and need at least {2} "
                   "more.".format(waited, count, curr_minimum - count))

    # Wait to make sure that the encrypted drive is mounted.
    print ("Waiting 120 seconds for nodes to launch and to ensure that the "
           "encrypted drive is mounted on all new instances.")
    time.sleep(120)

    # Reload the environment to add the new web servers.
    executel(environment, deployment_tag)

    # Show the upgrade message on all servers, new and old, so that no user
    # will be able to access the site.
    executel('begin_upgrade')

    # make sure we deploy the same changeset as was used in the launch config
    changeset = launch_config.name.split('_')[-1]
    executel('deploy_worker', changeset=changeset)

    # It's safe to add to the load balancer now, since all servers have the
    # upgrade message.
    group.resume_processes(["AddToLoadBalancer"])
    print "Resumed 'AddToLoadBalancer' autoscaling process."

    # Even though AddToLoadBalancer has resumed, we must manually add
    # the just-created instances to the load balancer(s) and wait for them to
    # be healthy in the load balancer(s).
    print "Waiting for new instances to be InService with the load balancer(s)."
    add_all_to_elb()

    old_instances = [i for i in group.instances
                     if i.launch_config_name != group.launch_config_name]

    # Ensure that the group will kill the oldest servers (in this case, the
    # servers using the previous launch configuration) first.
    curr_policies = group.termination_policies
    group.termination_policies = ['OldestInstance']
    group.update()
    print "Updated the termination policy to 'OldestInstance'."

    # Reset the group's minimum and desired number of servers.
    group.min_size = curr_minimum
    group.desired_capacity = curr_desired
    group.update()
    print "Reset minimum and desired number of servers."

    # Wait for the old instances to be killed.
    for elb_name in env.elb_names:
        for old_instance in old_instances:
            print ("Waiting for {0} to be OutOfService with the load "
                   "balancer {1}.".format(old_instance.instance_id, elb_name))
            _wait_for_elb_state(elb_name, old_instance.instance_id,
                                "OutOfService")

    # Reset the group's termination policies.
    group.termination_policies = curr_policies
    group.update()
    print "Reset the termination policies."

    # Reload the environment to remove the old web servers.
    executel(environment, deployment_tag)

    # Remove the upgrade message so that the users can access the site again.
    executel('end_upgrade')


@task
@runs_once
def deploy_serial(deployment_tag, environment, launch_config_name=None, answer=None):
    """Autoscaling replacement for deploy_serial_without_autoscaling.

    Safely deploy to the specified environment with no downtime, by updating
    the existing autoscaling group to use a new launch configuration, killing
    off old instances one by one, and allowing the autoscaling group to bring
    up new instances as needed.
    """
    _check_local_deps()
    executel(environment, deployment_tag, answer=answer)

    if not launch_config_name:
        launch_config = _create_launch_config()
    else:
        launch_config = _get_launch_config(launch_config_name)

    # make sure we deploy the same changeset as was used in the launch config
    changeset = launch_config.name.split('_')[-1]
    executel('deploy_worker', changeset=changeset)

    # Update the existing autoscaling group to use the new launch config.
    autoscaling_group = _update_autoscaling_group(launch_config)

    # Bring down each old instance in turn and allow the autoscaling group to
    # recreate it (if needed) using the new launch config.
    _refresh_instances(autoscaling_group)

    print "Completed deployment with autoscaling."


def _ag_instances(autoscaling_group, current=True):
    """
    Returns a list of instances in the specified autoscaling group. If
    ``current`` is True the instances returned will be those instances that
    use the currently configured launch config; otherwise, all other (non-current)
    instances will be returned.
    """
    return [i for i in autoscaling_group.instances
            if (current and i.launch_config_name == autoscaling_group.launch_config_name) or
               (not current and i.launch_config_name != autoscaling_group.launch_config_name)]


def _ag_inst_states(autoscaling_group):
    """
    Returns a dictionary of instance states where the key is a (elb_name, instance_id)
    tuple and the value is the string representation of the instance state.
    """
    instances = {}
    for elb_name in env.elb_names:
        for inst in _ag_instances(autoscaling_group, current=True):
            inst_id = inst.instance_id
            instances[(elb_name, inst_id)] = _elb_state(elb_name, inst_id)
    return instances


def _refresh_instances(autoscaling_group):
    """
    Brings down each non-current instance in turn and allows the autoscaling
    group to recreate it (if needed) using the current configuration.
    """
    conn = AutoScaleConnection()

    # NOTE: It takes longer for the load balancer(s) to finish bringing down/up
    # instances than it does for the autoscaling group, so for each server we
    # check the status according to the load balancer(s) before moving on to the
    # next.
    max_inst_create_time = 180 # seconds
    check_period = 5 # seconds
    old_instances = _ag_instances(autoscaling_group, current=False)
    print "Found {0} old instances.".format(len(old_instances))
    for old_instance in old_instances:
        print "Starting to bring down old instance with id {0}.".format(
               old_instance.instance_id)
        conn.set_instance_health(old_instance.instance_id, "Unhealthy")
        for elb_name in env.elb_names:
            print "Waiting for {0} to be out of service with load balancer {1}. "\
                  "Note: ignore any 'InvalidInstance' errors.".format(
                   old_instance.instance_id, elb_name)
            _wait_for_elb_state(elb_name, old_instance.instance_id,
                                "OutOfService")
        print "{0} is now out of service. Waiting for autoscaling group...".format(
               old_instance.instance_id)
        time.sleep(45)  # Wait for the autoscaling group to catch up.
                        # This time amount is just a guess - it seems to take
                        # that long for the group to decide whether or not to
                        # make a new instance, and the load balancer(s) to see it.
                        # Effective 5/21/15, this was changed from 30 to 45 because
                        # 30 didn't seem to be long enough.
        # If this is the first instance we're adding, make sure at least one new
        # one comes up before continuing.
        for i in range(max_inst_create_time/check_period):
            time.sleep(check_period)
            autoscaling_group = _get_autoscaling_group()  # Refresh instances list.
            # Wait for a new instance, if any, to be fully brought up.
            # (If we had more-than-the minimum instances before the upgrade, then
            # the autoscaling group might not bring up another immediately.)
            print "Checking for any new instances to be in service..."
            if _ag_instances(autoscaling_group, current=True):
                break
        else:
            print "WARNING: no new instances detected after %s seconds" % max_inst_create_time
        # Wait for all instances currently known to the auto scaling group to be in
        # service with each load balancer. We may get 400 Bad Request / Could not find
        # instance responses while this is in process.
        inst_states = _ag_inst_states(autoscaling_group)
        while not all([(s == 'InService') for s in inst_states.values()]):
            print "Waiting for the following instances to be in service:"
            for k, v in inst_states.items():
                if v != 'InService':
                    print '    %s: %s' % k # k is tuple of (elb_name, instance_id)
            time.sleep(10)
            # refresh instance states
            autoscaling_group = _get_autoscaling_group()  # Refresh instances list.
            inst_states = _ag_inst_states(autoscaling_group)
        print ("Finished bringing down old instance with id {0}.".format(
               old_instance.instance_id))
    print "All old instances have been terminated."


def _elb_state(elb_name, instance_id):
    """
    Returns the InstanceState for the instance in the specified load balancer.
    """
    conn = ELBConnection()
    try:
        return conn.describe_instance_health(elb_name, [instance_id])[0].state
    except BotoServerError:
        return "OutOfService"


def _wait_for_elb_state(elb_name, instance_id, state):
    """
    Waits for the instance to enter the a certain state in the load balancer.
    """
    waited = 0
    while True:
        print ("Have waited {0} seconds for {1} to be {2}...".format(waited, instance_id, state))
        if _elb_state(elb_name, instance_id) == state:
            return state
        time.sleep(5)
        waited += 5


def _create_server_for_image():
    """Creates a new web server for use in creating an AMI for auto scaling."""
    server = _retry_new(env.deployment_tag, env.environment, 'web',
                        avail_zone=env.avail_zones[0])[0]
    # return string rather than server itself since we might get run
    # in another UNIX process
    return server.instance.id


def _create_image_from_server(server):
    """Creates an AMI of a existing FabulAWS server."""
    now = datetime.datetime.utcnow().strftime('%Y.%m.%d-%H.%M.%S')
    try:
        with server:
            deploy_web()
            changeset = current_changeset()
        name = _instance_name('web', now, changeset)
        image = server.create_image(name=name)

        # The Name tag is set with the "-PENDING" server name, which at
        # this point is out-of-date. Removing it for clarity.
        image.remove_tag('Name')
    finally:
        server.cleanup()
    # reload the environment WITHOUT the new server
    _setup_env(env.deployment_tag, env.environment)
    print "Created a new AMI with id {0}.".format(image.id)
    return image


def _create_launch_config(server=None):
    """Returns a new launch configuration for the specified image."""
    # Create an AMI using the deploy code, and create a new launch config.
    created = server is None
    if server is None:
        instance_id = _create_server_for_image()
        # reload the environment WITH the new server
        _setup_env(env.deployment_tag, env.environment)
        server = _get_servers(env.deployment_tag, env.environment, 'web',
                              instance_ids=[instance_id])[0]
    try:
        image = _create_image_from_server(server)
        timestamp, changeset = image.name.split('_')[-2:]

        lc = LaunchConfiguration(
            name=_instance_name('lc', timestamp, changeset),
            image_id=image.id,
            security_groups=server.get_security_groups_for_launch_configuration(),
            instance_type=_find(env.instance_types, env.environment, 'web'),
            # Enable detailed monitoring for more responsive autoscaling; see:
            # https://docs.aws.amazon.com/autoscaling/ec2/userguide/as-instance-monitoring.html#enable-as-instance-metrics
            instance_monitoring=True,
        )
        AutoScaleConnection().create_launch_configuration(lc)
        print "Created a new launch config with name {0}.".format(lc.name)
        return lc
    finally:
        # if we created the server, clean it up here
        if created:
            server.terminate()


def _get_launch_config(name):
    """Retrieves the launch configuration with the given name."""
    configs = AutoScaleConnection().get_all_launch_configurations(names=[name])
    if not configs:
        raise Exception("Cannot find a launch configuration with the name "
                        "'{name}'.".format(name=name))
    if len(configs) > 2:
        raise Exception("Found more than one launch configuration with "
                        "the name '{name}'.".format(name=name))
    config = configs[0]
    print "Retrieved launch configuration named '{0}'.".format(config.name)
    return config


def _get_autoscaling_group(name=None):
    """Retrieves the autoscaling group for this environment.

    Assumes it already exists, and that there is only one.
    """
    name = name or env.ag_name
    groups = AutoScaleConnection().get_all_groups(names=[name])
    if not groups:
        raise Exception("Cannot find an autoscaling group with the name "
                        "'{name}'. For now it must be manually created ahead "
                        "of time.".format(name=name))
    elif len(groups) >= 2:
        raise Exception("Found more than one autoscaling group with "
                        "the name '{name}'.".format(name=name))
    print "Retrieved auto scaling group named '{0}'.".format(groups[0].name)
    return groups[0]


def _update_autoscaling_group(launch_config):
    """Updates the existing autoscaling group to use a new launch_config."""
    group = _get_autoscaling_group()

    # Update to the new launch configuration.
    group.launch_config_name = launch_config.name
    group.update()

    # Make sure that the appropriate tags exist, and that they are set
    # to propagate when a new server is created.
    AutoScaleConnection().create_or_update_tags([
        Tag(key="Name", value=_instance_name("web"),
            propagate_at_launch=True, resource_id=group.name),
        Tag(key="environment", value=env.environment,
            propagate_at_launch=True, resource_id=group.name),
        Tag(key="deployment", value=env.deployment_tag,
            propagate_at_launch=True, resource_id=group.name),
        Tag(key="role", value="web",
            propagate_at_launch=True, resource_id=group.name),
    ])

    print ("Autoscaling group {0} has been updated to use launch config "
           "{1}.".format(group.name, launch_config.name))

    return group
