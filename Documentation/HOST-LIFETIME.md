<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
# Host ownership and topology synchronization

A host has two kinds of owners: the topology and callers holding explicit
references. The topology owns the initial reference. `libnvme_get_host()`
and the C host iterators return borrowed pointers; they do not transfer it.

Use `libnvme_host_ref()` to retain a borrowed host and match every acquired
reference with `libnvme_host_unref()`. The last unref destroys the host.
It does not remove a live tree's ownership on behalf of the caller.

`libnvme_free_host()` has a separate role: it detaches the host, clears its
subsystems, and drops the topology's reference. It leaves other owners with
an empty, valid host. Calling it again on a retained, detached host does not
release another reference.

Each host also retains its global context. `libnvme_free_global_ctx()` first
detaches every host, then releases the caller's context ownership. A retained
host keeps its parent context allocated until its final unref. This breaks
the topology/context ownership cycle during explicit teardown.

`libnvme_refresh_topology()` detaches the old hosts and scans a new topology.
Old referenced hosts retain their identity, but their subsystem lists are
empty. Dropping an old reference cannot remove a replacement host from the
new tree. Subsystem, controller and namespace pointers still become invalid
when their owner removes them; this change only reference-counts hosts.

## Threads

Atomic reference counting protects reference updates, not field access or
borrowed pointers. Serialize shared topology operations with the recursive
`libnvme_topology_lock()` and `libnvme_topology_unlock()` functions. Keep the
context alive and stop other users before destroying its owner.

For example, lookup and acquisition must be one critical section:

```c
libnvme_topology_lock(ctx);
err = libnvme_get_host(ctx, hostnqn, hostid, &host);
if (!err)
	libnvme_host_ref(host);
libnvme_topology_unlock(ctx);
/* On success, host remains allocated until libnvme_host_unref(host). */
```

Host insertion, removal, topology scans and `libnvmf_add_ctrl()` use the same
lock. Other traversal or modification of shared topology must follow the
locking contract too; the library does not make every object operation
automatically thread-safe. In particular, a retained host does not protect
borrowed subsystem or controller pointers against concurrent removal.

Python `Host()` acquires its reference under the topology lock. `hosts()`
takes a snapshot of referenced wrappers under that lock, then releases the
lock before yielding. The wrappers release their references at destruction.
The lock is not held while Python user code consumes the iterator.

## Reference diagnostics

`LIBNVME_REF_DEBUG=1` enables a separate stderr log containing the operation,
host address, resulting count and caller location. The C setting is sampled
once, at the first ref or unref. Python samples it at module import and only
inspects caller frames when enabled. Set it before starting the process;
changing the environment later does not reconfigure diagnostics.

The exported `_at()` backing functions keep their existing names in this
proposal. Any alternative prefix requires agreement before the API is merged.
The new topology lock functions are listed in the `LIBNVME_3.1` version node.
