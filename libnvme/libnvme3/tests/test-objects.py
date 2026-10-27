#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Unit tests for the libnvme Python bindings.

These tests cover object creation, property access, and error handling.
They do not require real NVMe hardware to run.
"""
import contextlib
import errno
import gc
import os
import subprocess
import sys
import unittest
from unittest import mock
from libnvme3 import nvme


def _drain(fd):
    """Read everything currently buffered on a non-blocking fd."""
    chunks = []
    while True:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b''.join(chunks).decode(errors='replace')


@contextlib.contextmanager
def capture_libnvme_ref_debug_log():
    """Capture everything libnvme's ref/unref debug log writes to the
    real OS-level stderr fd (LIBNVME_REF_DEBUG is read by C code that
    calls fprintf(stderr, ...), so sys.stderr monkeypatching won't see
    it -- only an fd-level redirect does). Yields a callable that
    returns everything captured so far, without blocking.
    """
    stderr_fd = 2
    saved_fd = os.dup(stderr_fd)
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    os.dup2(write_fd, stderr_fd)
    os.close(write_fd)
    try:
        yield lambda: _drain(read_fd)
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(saved_fd)
        os.close(read_fd)


class TestConstants(unittest.TestCase):
    """Verify that well-known constants are accessible and have correct values."""

    def test_disc_subsys_name_is_string(self):
        self.assertIsInstance(nvme.NVME_DISC_SUBSYS_NAME, str)

    def test_disc_subsys_name_value(self):
        self.assertEqual(nvme.NVME_DISC_SUBSYS_NAME, 'nqn.2014-08.org.nvmexpress.discovery')

    def test_log_lid_discovery_is_int(self):
        self.assertIsInstance(nvme.NVME_LOG_LID_DISCOVERY, int)



class TestGlobalCtx(unittest.TestCase):

    def test_creation_no_args(self):
        ctx = nvme.GlobalCtx()
        self.assertIsNotNone(ctx)

    def test_context_manager(self):
        with nvme.GlobalCtx() as ctx:
            self.assertIsNotNone(ctx)

    def test_context_manager_methods_accessible(self):
        with nvme.GlobalCtx() as ctx:
            hosts = list(ctx.hosts())
            self.assertIsInstance(hosts, list)

    def test_hosts_iterator_returns_list(self):
        ctx = nvme.GlobalCtx()
        hosts = list(ctx.hosts())
        self.assertIsInstance(hosts, list)

    def test_refresh_topology_does_not_raise(self):
        ctx = nvme.GlobalCtx()
        ctx.refresh_topology()

    def test_log_level_all_valid_levels(self):
        ctx = nvme.GlobalCtx()
        for level in ('debug', 'info', 'warning', 'err'):
            with self.subTest(level=level):
                ctx.log_level(level)


class TestHost(unittest.TestCase):

    def setUp(self):
        self.ctx = nvme.GlobalCtx()
        (hostnqn, hostid) = nvme.host_get_ids(self.ctx)
        self.ctx.hostnqn = hostnqn
        self.ctx.hostid = hostid

    def tearDown(self):
        self.ctx = None
        gc.collect()

    def test_creation_default(self):
        host = nvme.Host(self.ctx)
        self.assertIsNotNone(host)

    def test_creation_with_explicit_hostnqn(self):
        hostnqn = 'nqn.2014-08.com.example:test-host-creation'
        host = nvme.Host(self.ctx, hostnqn=hostnqn)
        self.assertIsNotNone(host)
        self.assertEqual(host.hostnqn, hostnqn)

    def test_creation_with_hostnqn_and_hostid(self):
        hostnqn = 'nqn.2014-08.com.example:test-host-props'
        hostid = '11111111-2222-3333-4444-555555555555'
        host = nvme.Host(self.ctx, hostnqn=hostnqn, hostid=hostid)
        self.assertEqual(host.hostnqn, hostnqn)
        self.assertEqual(host.hostid, hostid)

    def test_creation_with_hostsymname(self):
        hostnqn = 'nqn.2014-08.com.example:test-host-symname'
        symname = 'my-storage-host'
        host = nvme.Host(self.ctx, hostnqn=hostnqn, hostsymname=symname)
        self.assertEqual(host.hostsymname, symname)

    def test_set_hostsymname(self):
        hostnqn = 'nqn.2014-08.com.example:test-host-set-symname'
        host = nvme.Host(self.ctx, hostnqn=hostnqn)
        host.hostsymname = 'updated-symname'
        self.assertEqual(host.hostsymname, 'updated-symname')

    def test_kxchap_host_key_is_none_by_default(self):
        hostnqn = 'nqn.2014-08.com.example:test-host-kxchap'
        host = nvme.Host(self.ctx, hostnqn=hostnqn)
        self.assertIsNone(host.kxchap_host_key)

    def test_subsystems_iterator_returns_list(self):
        host = nvme.Host(self.ctx)
        subsystems = list(host.subsystems())
        self.assertIsInstance(subsystems, list)

    def test_str_contains_class_name(self):
        host = nvme.Host(self.ctx)
        self.assertIn('nvme.Host', str(host))

    def test_context_manager(self):
        with nvme.Host(self.ctx) as h:
            self.assertIsNotNone(h)

    def test_context_manager_properties_accessible(self):
        hostnqn = 'nqn.2014-08.com.example:test-host-ctx-mgr'
        with nvme.Host(self.ctx, hostnqn=hostnqn) as h:
            self.assertEqual(h.hostnqn, hostnqn)
            self.assertIsNone(h.kxchap_host_key)


class TestCtrl(unittest.TestCase):

    def setUp(self):
        self.ctx = nvme.GlobalCtx()
        (hostnqn, hostid) = nvme.host_get_ids(self.ctx)
        self.ctx.hostnqn = hostnqn
        self.ctx.hostid = hostid
        self.subsysnqn = nvme.NVME_DISC_SUBSYS_NAME

    def tearDown(self):
        self.ctx = None
        gc.collect()

    def _make_loop_ctrl(self):
        return nvme.Ctrl(self.ctx, {
            'subsysnqn': self.subsysnqn,
            'transport': 'loop',
        })

    def test_creation_loop_transport(self):
        ctrl = self._make_loop_ctrl()
        self.assertIsNotNone(ctrl)

    def test_creation_tcp_transport_with_traddr(self):
        ctrl = nvme.Ctrl(self.ctx, {
            'subsysnqn': self.subsysnqn,
            'transport': 'tcp',
            'traddr': '192.168.1.1',
            'trsvcid': '4420',
        })
        self.assertIsNotNone(ctrl)

    def test_transport_property(self):
        ctrl = self._make_loop_ctrl()
        self.assertEqual(ctrl.transport, 'loop')

    def test_subsysnqn_property(self):
        ctrl = self._make_loop_ctrl()
        self.assertEqual(ctrl.subsysnqn, self.subsysnqn)

    def test_traddr_property(self):
        ctrl = nvme.Ctrl(self.ctx, {
            'subsysnqn': self.subsysnqn,
            'transport': 'tcp',
            'traddr': '10.0.0.1',
        })
        self.assertEqual(ctrl.traddr, '10.0.0.1')

    def test_trsvcid_property(self):
        ctrl = nvme.Ctrl(self.ctx, {
            'subsysnqn': self.subsysnqn,
            'transport': 'tcp',
            'traddr': '10.0.0.1',
            'trsvcid': '8009',
        })
        self.assertEqual(ctrl.trsvcid, '8009')

    def test_connected_returns_false_before_connect(self):
        ctrl = self._make_loop_ctrl()
        self.assertFalse(ctrl.connected)

    def test_name_is_none_before_connect(self):
        ctrl = self._make_loop_ctrl()
        self.assertIsNone(ctrl.name)

    def test_str_contains_transport(self):
        ctrl = self._make_loop_ctrl()
        s = str(ctrl)
        self.assertIn('loop', s)

    def test_context_manager(self):
        with nvme.Ctrl(self.ctx, {
            'subsysnqn': self.subsysnqn,
            'transport': 'loop',
        }) as c:
            self.assertIsNotNone(c)

    def test_context_manager_properties_accessible(self):
        with nvme.Ctrl(self.ctx, {
            'subsysnqn': self.subsysnqn,
            'transport': 'loop',
        }) as c:
            self.assertEqual(c.transport, 'loop')
            self.assertEqual(c.subsysnqn, self.subsysnqn)
            self.assertFalse(c.connected)

    def test_namespaces_iterator_returns_list(self):
        ctrl = self._make_loop_ctrl()
        nss = list(ctrl.namespaces())
        self.assertIsInstance(nss, list)

    def test_discovery_ctrl_flag_default_false(self):
        ctrl = self._make_loop_ctrl()
        self.assertFalse(ctrl.discovery_ctrl)

    def test_discovery_ctrl_flag_set_and_clear(self):
        ctrl = self._make_loop_ctrl()
        ctrl.discovery_ctrl = True
        self.assertTrue(ctrl.discovery_ctrl)
        ctrl.discovery_ctrl = False
        self.assertFalse(ctrl.discovery_ctrl)

    def test_persistent_flag_default_false(self):
        ctrl = self._make_loop_ctrl()
        self.assertFalse(ctrl.persistent)

    def test_persistent_flag_set(self):
        ctrl = self._make_loop_ctrl()
        ctrl.persistent = True
        self.assertTrue(ctrl.persistent)

    def test_unique_discovery_ctrl_flag(self):
        ctrl = self._make_loop_ctrl()
        ctrl.unique_discovery_ctrl = True
        self.assertTrue(ctrl.unique_discovery_ctrl)

    def test_multiple_ctrls_same_ctx(self):
        """Multiple controllers can be created under the same context."""
        ctrls = [self._make_loop_ctrl() for _ in range(5)]
        self.assertEqual(len(ctrls), 5)
        for c in ctrls:
            self.assertFalse(c.connected)


class TestExceptions(unittest.TestCase):
    """Exception hierarchy exposed via the nvme module."""

    def test_nvme_error_importable(self):
        self.assertTrue(hasattr(nvme, 'NvmeError'))

    def test_connect_error_importable(self):
        self.assertTrue(hasattr(nvme, 'ConnectError'))

    def test_disconnect_error_importable(self):
        self.assertTrue(hasattr(nvme, 'DisconnectError'))

    def test_discover_error_importable(self):
        self.assertTrue(hasattr(nvme, 'DiscoverError'))

    def test_not_connected_error_importable(self):
        self.assertTrue(hasattr(nvme, 'NotConnectedError'))

    def test_subclasses_inherit_from_nvme_error(self):
        for cls in (nvme.ConnectError, nvme.DisconnectError,
                    nvme.DiscoverError, nvme.NotConnectedError):
            with self.subTest(cls=cls):
                self.assertTrue(issubclass(cls, nvme.NvmeError))

    def test_nvme_error_is_exception(self):
        self.assertTrue(issubclass(nvme.NvmeError, Exception))

    def test_nvme_error_has_errno_and_message(self):
        e = nvme.NvmeError(5, 'test message')
        self.assertEqual(e.errno, 5)
        self.assertEqual(e.message, 'test message')

    def test_not_connected_error_no_errno_arg(self):
        e = nvme.NotConnectedError()
        self.assertEqual(e.errno, 0)

    def test_not_connected_error_custom_message(self):
        e = nvme.NotConnectedError("custom msg")
        self.assertEqual(e.message, "custom msg")


class TestCtrlErrorHandling(unittest.TestCase):
    """Error paths that can be exercised without real hardware."""

    def setUp(self):
        self.ctx = nvme.GlobalCtx()
        (hostnqn, hostid) = nvme.host_get_ids(self.ctx)
        self.ctx.hostnqn = hostnqn
        self.ctx.hostid = hostid
        self.ctrl = nvme.Ctrl(self.ctx, {
            'subsysnqn': nvme.NVME_DISC_SUBSYS_NAME,
            'transport': 'loop',
        })

    def tearDown(self):
        self.ctrl = None
        self.ctx = None
        gc.collect()

    def test_disconnect_unconnected_raises_not_connected_error(self):
        with self.assertRaises(nvme.NotConnectedError):
            self.ctrl.disconnect()

    def test_discover_unconnected_raises_not_connected_error(self):
        with self.assertRaises(nvme.NotConnectedError):
            self.ctrl.discover()

    def test_error_message_is_the_errno_text(self):
        # A hostid without a hostnqn fails with -EINVAL from libnvme.
        ctx = nvme.GlobalCtx()
        with self.assertRaises(nvme.NvmeError) as cm:
            nvme.Ctrl(ctx, {
                'subsysnqn': nvme.NVME_DISC_SUBSYS_NAME,
                'transport': 'pcie',
                'hostid': 'c3d4e5f6-0000-4000-8000-000000000003',
            })
        self.assertEqual(cm.exception.errno, -errno.EINVAL)
        self.assertEqual(cm.exception.message, os.strerror(errno.EINVAL))


@unittest.skipUnless(nvme._REF_DEBUG, 'requires LIBNVME_REF_DEBUG at startup')
class TestHostRefCounting(unittest.TestCase):
    """Host objects obtained via ctx.hosts() must take/release a real
    libnvme refcount on the underlying C object (see issue #3736),
    not just extend the parent ctx's Python lifetime via __parent.
    """

    def setUp(self):
        self.ctx = nvme.GlobalCtx()
        (hostnqn, hostid) = nvme.host_get_ids(self.ctx)
        self.ctx.hostnqn = hostnqn
        self.ctx.hostid = hostid
        # Created before capturing starts, so only the iterator's own
        # ref/unref show up in the captured window below.
        self.host = nvme.Host(self.ctx)

    def tearDown(self):
        self.host = None
        self.ctx = None
        gc.collect()

    def test_iterator_refs_and_unrefs_the_host(self):
        with capture_libnvme_ref_debug_log() as drain:
            hosts = list(self.ctx.hosts())
            self.assertEqual(len(hosts), 1)
            after_iterate = drain()

            del hosts
            gc.collect()
            after_drop = drain()

        self.assertIn('ref host=', after_iterate)
        self.assertIn('unref host=', after_drop)

    def test_iterator_ref_logs_the_real_caller_location(self):
        """The ref debug log must name this test file and a real line
        number -- the caller's actual location -- not a fixed
        placeholder string baked into nvme.i.
        """
        with capture_libnvme_ref_debug_log() as drain:
            list(self.ctx.hosts())
            after_iterate = drain()

        self.assertIn(os.path.basename(__file__), after_iterate)
        self.assertNotIn('nvme.i', after_iterate)

    def test_constructor_ref_logs_the_real_caller_location(self):
        """Same requirement as above, for the Host() constructor path."""
        with capture_libnvme_ref_debug_log() as drain:
            nvme.Host(self.ctx)
            after_ctor = drain()

        self.assertIn(os.path.basename(__file__), after_ctor)
        self.assertNotIn('nvme.i', after_ctor)

    def test_destructor_unref_logs_gc_marker(self):
        """Destructor runs from GC, not caller code; must log "<gc>", not a
        fake location.
        """
        with capture_libnvme_ref_debug_log() as drain:
            host = nvme.Host(self.ctx)
            drain()  # discard the constructor's own ref line
            del host
            gc.collect()
            after_drop = drain()

        self.assertIn('unref host=', after_drop)
        self.assertIn('<gc>', after_drop)

    def test_debug_setting_is_cached(self):
        setting = os.environ.pop('LIBNVME_REF_DEBUG', None)
        try:
            with capture_libnvme_ref_debug_log() as drain:
                nvme.Host(self.ctx)
                output = drain()
            self.assertIn('ref host=', output)
        finally:
            if setting is not None:
                os.environ['LIBNVME_REF_DEBUG'] = setting


class TestHostLifetime(unittest.TestCase):
    NQN = 'nqn.2014-08.org.nvmexpress:uuid:11111111-2222-3333-4444-555555555555'

    def test_refresh_detaches_held_host(self):
        ctx = nvme.GlobalCtx()
        host = nvme.Host(ctx, hostnqn=self.NQN)
        held = list(ctx.hosts())
        ctx.refresh_topology()
        self.assertEqual(host.hostnqn, self.NQN)
        self.assertEqual(held[0].hostnqn, self.NQN)
        self.assertEqual(list(host.subsystems()), [])
        self.assertNotIn(self.NQN, [h.hostnqn for h in ctx.hosts()])

        replacement = nvme.Host(ctx, hostnqn=self.NQN)
        del held, host
        gc.collect()
        self.assertIn(self.NQN, [h.hostnqn for h in ctx.hosts()])
        self.assertEqual(replacement.hostnqn, self.NQN)

    def test_iterator_survives_refresh_between_yields(self):
        ctx = nvme.GlobalCtx()
        nvme.Host(ctx, hostnqn=self.NQN)
        nvme.Host(ctx, hostnqn=self.NQN + '-second')
        iterator = ctx.hosts()
        first = next(iterator)
        ctx.refresh_topology()
        second = next(iterator)
        self.assertEqual({first.hostnqn, second.hostnqn},
                         {self.NQN, self.NQN + '-second'})
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_iterator_host_survives_context_wrapper(self):
        ctx = nvme.GlobalCtx()
        nvme.Host(ctx, hostnqn=self.NQN)
        host = list(ctx.hosts())[0]
        del ctx
        gc.collect()
        self.assertEqual(host.hostnqn, self.NQN)
        del host
        gc.collect()

    def test_repeated_iterator_wrapper_collection(self):
        for _ in range(20):
            ctx = nvme.GlobalCtx()
            nvme.Host(ctx, hostnqn=self.NQN)
            hosts = list(ctx.hosts())
            self.assertIsInstance(hosts[0], nvme.Host)
            del hosts, ctx
            gc.collect()

    def test_module_shutdown_with_iterator_host(self):
        code = (
            'from libnvme3 import nvme\n'
            'ctx = nvme.GlobalCtx()\n'
            f'nvme.Host(ctx, hostnqn={self.NQN!r})\n'
            'for h in ctx.hosts():\n'
            '    print(h.hostnqn)\n'
        )
        result = subprocess.run([sys.executable, '-c', code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.NQN, result.stdout)
        self.assertNotIn('AddressSanitizer', result.stderr)

    def test_waiting_for_topology_lock_releases_gil(self):
        code = (
            'import threading, time\n'
            'from libnvme3 import nvme\n'
            'ctx = nvme.GlobalCtx()\n'
            'entered = threading.Event()\n'
            'def acquire_host():\n'
            '    entered.set()\n'
            f'    nvme.Host(ctx, hostnqn={self.NQN!r})\n'
            'nvme.libnvme_topology_lock(ctx)\n'
            'worker = threading.Thread(target=acquire_host)\n'
            'worker.start()\n'
            'assert entered.wait(2)\n'
            'time.sleep(0.02)\n'
            'nvme.libnvme_topology_unlock(ctx)\n'
            'worker.join(2)\n'
            'assert not worker.is_alive()\n'
        )
        result = subprocess.run([sys.executable, '-c', code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(nvme._REF_DEBUG, 'debug mode records caller frames')
    def test_debug_disabled_does_not_inspect_frames(self):
        ctx = nvme.GlobalCtx()
        with mock.patch.object(sys, '_getframe', side_effect=AssertionError):
            host = nvme.Host(ctx, hostnqn=self.NQN)
            hosts = list(ctx.hosts())
        self.assertEqual(hosts[0].hostnqn, host.hostnqn)


class TestHelperFunctions(unittest.TestCase):
    """Module-level helper functions exposed by the bindings."""

    def setUp(self):
        self.ctx = nvme.GlobalCtx()

    def test_read_hostnqn_returns_string_or_none(self):
        hostnqn = nvme.read_hostnqn(self.ctx)
        self.assertIsInstance(hostnqn, (str, type(None)))

    def test_read_hostid_returns_string_or_none(self):
        hostid = nvme.read_hostid(self.ctx)
        self.assertIsInstance(hostid, (str, type(None)))


if __name__ == '__main__':
    unittest.main()
