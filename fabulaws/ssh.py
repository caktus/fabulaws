import os
import time
import logging
import paramiko
import socket
import threading

from StringIO import StringIO

logger = logging.getLogger('fabulaws.ssh')

class LoggingReader(threading.Thread):

    def __init__(self, read_from, logger, level):
        super(LoggingReader, self).__init__()
        self.read_from = read_from
        self.logger = logger
        self.level = level

    def run(self):
        def closed(stream):
            if hasattr(stream, 'channel'):
                return stream.channel.closed
            else:
                return stream.closed
        while not closed(self.read_from):
            line = self.read_from.readline().strip()
            if line:
                self.logger.log(self.level, line)


class SSH(object):

    retry_wait = 2 # seconds
    retry_times = 60
    shell = '/bin/bash -l -c'
    
    _ssh = None
    _sftp = None
    
    @property
    def sftp(self):
        if not self._sftp:
            from fabulaws.sftp import SFTP
            self._sftp = SFTP(self)
        return self._sftp

    def __init__(self, host_name, username, key_filename):
        """
        Establishes a Paramiko SSHClient connection using the given host_name
        and key_filename.
        """
        logger.info('Establishing SSH connection')
        #pkey = paramiko.RSAKey.from_private_key(StringIO(self.key.material))
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        times = 0
        while times < self.retry_times:
            try:
                ssh.connect(host_name, allow_agent=False, look_for_keys=False,
                            username=username, key_filename=key_filename)
                break
            except (socket.error, EOFError), e:
                # Connection timed out or refused
                if isinstance(e, EOFError) or e.errno in (110, 111):
                    logger.debug('Error connecting, retrying in {0} '
                                 'seconds'.format(self.retry_wait))
                    times += 1
                    time.sleep(self.retry_wait)
                else:
                    raise
        ssh.exec_command('ls')
        self._ssh = ssh

    def _shell_escape(self, string):
        """
        Escape double quotes, backticks and dollar signs in given ``string``.

        For example::

            >>> _shell_escape('abc$')
            'abc\\\\$'
            >>> _shell_escape('"')
            '\\\\"'
        """
        for char in ('"', '$', '`'):
            string = string.replace(char, '\{0}'.format(char))
        return string

    def _shell_wrap(self, command, sudo_prefix=None):
        """
        Wrap given command in self.shell (while honoring sudo)
        """
        # Sudo plus space, or empty string
        if sudo_prefix is None:
            sudo_prefix = ''
        else:
            sudo_prefix += ' '
        # If we're shell wrapping, prefix shell and space, escape the command
        # and then quote it. Otherwise, empty string.
        shell = self.shell + ' '
        command = '"%s"' % self._shell_escape(command)
        # Resulting string should now have correct formatting
        return sudo_prefix + shell + command

    def _run_command(self, cmd, bufsize=-1):
        chan = self._ssh.get_transport().open_session()
        chan.exec_command(cmd)
        stdin = chan.makefile('wb', bufsize)
        stdout = chan.makefile('rb', bufsize)
        stderr = chan.makefile_stderr('rb', bufsize)
        out_thread = LoggingReader(stdout, logger, logging.INFO)
        err_thread = LoggingReader(stderr, logger, logging.ERROR)
        out_thread.start()
        err_thread.start()
        out_thread.join()
        err_thread.join()
        exit_status = chan.recv_exit_status()
        if exit_status != 0:
            raise Exception('Received non-zero exit status from command {0}: '
                            '{1}'.format(cmd, exit_status))

    def sudo(self, command):
        logger.info('sudo: {0}'.format(command))
        self._run_command(self._shell_wrap(command, sudo_prefix='sudo'))

    def run(self, command):
        logger.info('run: {0}'.format(command))
        self._run_command(self._shell_wrap(command))

    def put(self, local_path=None, remote_path=None, use_sudo=False,
        mirror_local_mode=False, mode=None):
        """
        Upload one or more files to a remote host.

        `~fabric.operations.put` returns an iterable containing the absolute file
        paths of all remote files uploaded. This iterable also exhibits a
        ``.failed`` attribute containing any local file paths which failed to
        upload (and may thus be used as a boolean test.) You may also check
        ``.succeeded`` which is equivalent to ``not .failed``.

        ``local_path`` may be a relative or absolute local file or directory path,
        and may contain shell-style wildcards, as understood by the Python ``glob``
        module.  Tilde expansion (as implemented by ``os.path.expanduser``) is also
        performed.

        ``local_path`` may alternately be a file-like object, such as the result of
        ``open('path')`` or a ``StringIO`` instance.

        .. note::
            In this case, `~fabric.operations.put` will attempt to read the entire
            contents of the file-like object by rewinding it using ``seek`` (and
            will use ``tell`` afterwards to preserve the previous file position).

        .. note::
            Use of a file-like object in `~fabric.operations.put`'s ``local_path``
            argument will cause a temporary file to be utilized due to limitations
            in our SSH layer's API.

        ``remote_path`` may also be a relative or absolute location, but applied to
        the remote host. Relative paths are relative to the remote user's home
        directory, but tilde expansion (e.g. ``~/.ssh/``) will also be performed if
        necessary.

        An empty string, in either path argument, will be replaced by the
        appropriate end's current working directory.

        While the SFTP protocol (which `put` uses) has no direct ability to upload
        files to locations not owned by the connecting user, you may specify
        ``use_sudo=True`` to work around this. When set, this setting causes `put`
        to upload the local files to a temporary location on the remote end, and
        then use `sudo` to move them to ``remote_path``.

        In some use cases, it is desirable to force a newly uploaded file to match
        the mode of its local counterpart (such as when uploading executable
        scripts). To do this, specify ``mirror_local_mode=True``.

        Alternately, you may use the ``mode`` kwarg to specify an exact mode, in
        the same vein as ``os.chmod`` or the Unix ``chmod`` command.

        `~fabric.operations.put` will honor `~fabric.context_managers.cd`, so
        relative values in ``remote_path`` will be prepended by the current remote
        working directory, if applicable. Thus, for example, the below snippet
        would attempt to upload to ``/tmp/files/test.txt`` instead of
        ``~/files/test.txt``::

            with cd('/tmp'):
                put('/path/to/local/test.txt', 'files')

        Use of `~fabric.context_managers.lcd` will affect ``local_path`` in the
        same manner.

        Examples::

            put('bin/project.zip', '/tmp/project.zip')
            put('*.py', 'cgi-bin/')
            put('index.html', 'index.html', mode=0755)

        .. versionchanged:: 1.0
            Now honors the remote working directory as manipulated by
            `~fabric.context_managers.cd`, and the local working directory as
            manipulated by `~fabric.context_managers.lcd`.
        .. versionchanged:: 1.0
            Now allows file-like objects in the ``local_path`` argument.
        .. versionchanged:: 1.0
            Directories may be specified in the ``local_path`` argument and will
            trigger recursive uploads.
        .. versionchanged:: 1.0
            Return value is now an iterable of uploaded remote file paths which
            also exhibits the ``.failed`` and ``.succeeded`` attributes.
        """
        # Handle empty local path
        local_path = local_path or os.getcwd()

        # Test whether local_path is a path or a file-like object
        local_is_path = not (hasattr(local_path, 'read') \
            and callable(local_path.read))
        
        # Expand tildes (assumption: default remote cwd is user $HOME)
        home = self.sftp.normalize('.')

        # Empty remote path implies cwd
        remote_path = remote_path or home

        # Honor cd() (assumes Unix style file paths on remote end)
        #if not os.path.isabs(remote_path) and env.get('cwd'):
        #    remote_path = env.cwd.rstrip('/') + '/' + remote_path

        if local_is_path:
            # Expand local paths
            local_path = os.path.expanduser(local_path)
            # Honor lcd() where it makes sense
            #if not os.path.isabs(local_path) and env.lcwd:
            #    local_path = os.path.join(env.lcwd, local_path)

            # Glob local path
            names = glob(local_path)
        else:
            names = [local_path]

        # Make sure local arg exists
        if local_is_path and not names:
            err = "'%s' is not a valid local path or glob." % local_path
            raise ValueError(err)

        # Sanity check and wierd cases
        if self.sftp.exists(remote_path):
            if local_is_path and len(names) != 1 and not self.sftp.isdir(remote_path):
                raise ValueError("'%s' is not a directory" % remote_path)

        # Iterate over all given local files
        remote_paths = []
        failed_local_paths = []
        for lpath in names:
            try:
                if local_is_path and os.path.isdir(lpath):
                    p = self.sftp.put_dir(lpath, remote_path, use_sudo,
                        mirror_local_mode, mode)
                    remote_paths.extend(p)
                else:
                    p = self.sftp.put(lpath, remote_path, use_sudo, mirror_local_mode,
                        mode, local_is_path)
                    remote_paths.append(p)
            except Exception, e:
                msg = "put() encountered an exception while uploading '%s'"
                failure = lpath if local_is_path else "<StringIO>"
                failed_local_paths.append(failure)
                _handle_failure(message=msg % lpath, exception=e)

        ret = _AttributeList(remote_paths)
        ret.failed = failed_local_paths
        ret.succeeded = not ret.failed
        return ret

    def get(self, remote_path, local_path=None):
        """
        Download one or more files from a remote host.

        `~fabric.operations.get` returns an iterable containing the absolute paths
        to all local files downloaded, which will be empty if ``local_path`` was a
        StringIO object (see below for more on using StringIO). This object will
        also exhibit a ``.failed`` attribute containing any remote file paths which
        failed to download, and a ``.succeeded`` attribute equivalent to ``not
        .failed``.

        ``remote_path`` is the remote file or directory path to download, which may
        contain shell glob syntax, e.g. ``"/var/log/apache2/*.log"``, and will have
        tildes replaced by the remote home directory. Relative paths will be
        considered relative to the remote user's home directory, or the current
        remote working directory as manipulated by `~fabric.context_managers.cd`.
        If the remote path points to a directory, that directory will be downloaded
        recursively.

        ``local_path`` is the local file path where the downloaded file or files
        will be stored. If relative, it will honor the local current working
        directory as manipulated by `~fabric.context_managers.lcd`. It may be
        interpolated, using standard Python dict-based interpolation, with the
        following variables:

        * ``host``: The value of ``env.host_string``, eg ``myhostname`` or
          ``user@myhostname-222`` (the colon between hostname and port is turned
          into a dash to maximize filesystem compatibility)
        * ``dirname``: The directory part of the remote file path, e.g. the
          ``src/projectname`` in ``src/projectname/utils.py``.
        * ``basename``: The filename part of the remote file path, e.g. the
          ``utils.py`` in ``src/projectname/utils.py``
        * ``path``: The full remote path, e.g. ``src/projectname/utils.py``.

        .. note::
            When ``remote_path`` is an absolute directory path, only the inner
            directories will be recreated locally and passed into the above
            variables. So for example, ``get('/var/log', '%(path)s')`` would start
            writing out files like ``apache2/access.log``,
            ``postgresql/8.4/postgresql.log``, etc, in the local working directory.
            It would **not** write out e.g.  ``var/log/apache2/access.log``.

            Additionally, when downloading a single file, ``%(dirname)s`` and
            ``%(path)s`` do not make as much sense and will be empty and equivalent
            to ``%(basename)s``, respectively. Thus a call like
            ``get('/var/log/apache2/access.log', '%(path)s')`` will save a local
            file named ``access.log``, not ``var/log/apache2/access.log``.

            This behavior is intended to be consistent with the command-line
            ``scp`` program.

        If left blank, ``local_path`` defaults to ``"%(host)s/%(path)s"`` in order
        to be safe for multi-host invocations.

        .. warning::
            If your ``local_path`` argument does not contain ``%(host)s`` and your
            `~fabric.operations.get` call runs against multiple hosts, your local
            files will be overwritten on each successive run!

        If ``local_path`` does not make use of the above variables (i.e. if it is a
        simple, explicit file path) it will act similar to ``scp`` or ``cp``,
        overwriting pre-existing files if necessary, downloading into a directory
        if given (e.g. ``get('/path/to/remote_file.txt', 'local_directory')`` will
        create ``local_directory/remote_file.txt``) and so forth.

        ``local_path`` may alternately be a file-like object, such as the result of
        ``open('path', 'w')`` or a ``StringIO`` instance.

        .. note::
            Attempting to `get` a directory into a file-like object is not valid
            and will result in an error.

        .. note::
            This function will use ``seek`` and ``tell`` to overwrite the entire
            contents of the file-like object, in order to be consistent with the
            behavior of `~fabric.operations.put` (which also considers the entire
            file). However, unlike `~fabric.operations.put`, the file pointer will
            not be restored to its previous location, as that doesn't make as much
            sense here and/or may not even be possible.

        .. note::
            Due to how our SSH layer works, a temporary file will still be written
            to your hard disk even if you specify a file-like object such as a
            StringIO for the ``local_path`` argument. Cleanup is performed,
            however -- we just note this for users expecting straight-to-memory
            transfers. (We hope to patch our SSH layer in the future to enable true
            straight-to-memory downloads.)

        .. versionchanged:: 1.0
            Now honors the remote working directory as manipulated by
            `~fabric.context_managers.cd`, and the local working directory as
            manipulated by `~fabric.context_managers.lcd`.
        .. versionchanged:: 1.0
            Now allows file-like objects in the ``local_path`` argument.
        .. versionchanged:: 1.0
            ``local_path`` may now contain interpolated path- and host-related
            variables.
        .. versionchanged:: 1.0
            Directories may be specified in the ``remote_path`` argument and will
            trigger recursive downloads.
        .. versionchanged:: 1.0
            Return value is now an iterable of downloaded local file paths, which
            also exhibits the ``.failed`` and ``.succeeded`` attributes.
        """
        # Handle empty local path / default kwarg value
        local_path = local_path or "%(host)s/%(path)s"

        # Test whether local_path is a path or a file-like object
        local_is_path = not (hasattr(local_path, 'write') \
            and callable(local_path.write))

        # Honor lcd() where it makes sense
        #if local_is_path and not os.path.isabs(local_path) and env.lcwd:
        #    local_path = os.path.join(env.lcwd, local_path)

        home = self.sftp.normalize('.')
        # Expand home directory markers (tildes, etc)
        if remote_path.startswith('~'):
            remote_path = remote_path.replace('~', home, 1)
        if local_is_path:
            local_path = os.path.expanduser(local_path)

        # Honor cd() (assumes Unix style file paths on remote end)
        if not os.path.isabs(remote_path):
            # Honor cwd if it's set (usually by with cd():)
            #if env.get('cwd'):
            #    remote_path = env.cwd.rstrip('/') + '/' + remote_path
            # Otherwise, be relative to remote home directory (SFTP server's
            # '.')
            #else:
            remote_path = os.path.join(home, remote_path)

        # Track final local destination files so we can return a list
        local_files = []
        failed_remote_files = []

        try:
            # Glob remote path
            names = self.sftp.glob(remote_path)

            # Handle invalid local-file-object situations
            if not local_is_path:
                if len(names) > 1 or self.sftp.isdir(names[0]):
                    _handle_failure("[%s] %s is a glob or directory, but local_path is a file object!" % (env.host_string, remote_path))

            for remote_path in names:
                if self.sftp.isdir(remote_path):
                    result = self.sftp.get_dir(remote_path, local_path)
                    local_files.extend(result)
                else:
                    # Result here can be file contents (if not local_is_path)
                    # or final resultant file path (if local_is_path)
                    result = self.sftp.get(remote_path, local_path, local_is_path,
                        os.path.basename(remote_path))
                    if not local_is_path:
                        # Overwrite entire contents of local_path
                        local_path.seek(0)
                        local_path.write(result)
                    else:
                        local_files.append(result)

        except Exception, e:
            failed_remote_files.append(remote_path)
            msg = "get() encountered an exception while downloading '%s'"
            _handle_failure(message=msg % remote_path, exception=e)

        ret = _AttributeList(local_files if local_is_path else [])
        ret.failed = failed_remote_files
        ret.succeeded = not ret.failed
        return ret
            
    def upload_template(filename, destination, context=None, use_jinja=False,
        template_dir=None, use_sudo=False, backup=True, mirror_local_mode=False,
        mode=None):
        """
        Render and upload a template text file to a remote host.

        ``filename`` should be the path to a text file, which may contain `Python
        string interpolation formatting
        <http://docs.python.org/release/2.5.4/lib/typesseq-strings.html>`_ and will
        be rendered with the given context dictionary ``context`` (if given.)

        Alternately, if ``use_jinja`` is set to True and you have the Jinja2
        templating library available, Jinja will be used to render the template
        instead. Templates will be loaded from the invoking user's current working
        directory by default, or from ``template_dir`` if given.

        The resulting rendered file will be uploaded to the remote file path
        ``destination``.  If the destination file already exists, it will be
        renamed with a ``.bak`` extension unless ``backup=False`` is specified.

        By default, the file will be copied to ``destination`` as the logged-in
        user; specify ``use_sudo=True`` to use `sudo` instead.

        The ``mirror_local_mode`` and ``mode`` kwargs are passed directly to an
        internal `~fabric.operations.put` call; please see its documentation for
        details on these two options.

        .. versionchanged:: 1.1
            Added the ``backup``, ``mirror_local_mode`` and ``mode`` kwargs.
        """
        func = use_sudo and self.sudo or self.run
        # Normalize destination to be an actual filename, due to using StringIO
        if func('test -d %s' % destination).succeeded:
            sep = "" if destination.endswith('/') else "/"
            destination += sep + os.path.basename(filename)

        # Use mode kwarg to implement mirror_local_mode, again due to using
        # StringIO
        if mirror_local_mode and mode is None:
            mode = os.stat(filename).st_mode
            # To prevent put() from trying to do this
            # logic itself
            mirror_local_mode = False

        # Process template
        text = None
        if use_jinja:
            try:
                from jinja2 import Environment, FileSystemLoader
                jenv = Environment(loader=FileSystemLoader(template_dir or '.'))
                text = jenv.get_template(filename).render(**context or {})
            except ImportError, e:
                abort("tried to use Jinja2 but was unable to import: %s" % e)
        else:
            with open(filename) as inputfile:
                text = inputfile.read()
            if context:
                text = text % context

        # Back up original file
        if backup and exists(destination):
            func("cp %s{,.bak}" % destination)

        # Upload the file.
        self.put(
            local_path=StringIO(text),
            remote_path=destination,
            use_sudo=use_sudo,
            mirror_local_mode=mirror_local_mode,
            mode=mode
        )

        def __del__(self):
            self._ssh.close()

