/*
 * Read-only Android/aarch64 kernel feature smoke probe.
 * Build locally with kernel_probe.sh; run explicitly as root on the target.
 * Every test runs in a clone child. The original process never installs a
 * seccomp filter, changes namespace, mounts a filesystem, or creates IPC.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <sched.h>
#include <signal.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/ipc.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#if !defined(__aarch64__)
#error "Build this probe for aarch64 Linux/Android."
#endif

typedef int (*probe_fn)(void);

static int failure(const char *test, const char *operation, int error)
{
	printf("FAIL %s operation=%s errno=%d (%s)\n",
	       test, operation, error, strerror(error));
	return 1;
}

/* No CLONE_VM: the child receives a private copy of the existing stack. */
static pid_t clone_process(unsigned long flags)
{
	return (pid_t)syscall(SYS_clone, flags | SIGCHLD, 0UL, 0UL, 0UL, 0UL);
}

static int reap(pid_t child, const char *test)
{
	int status;
	pid_t result;

	do {
		result = waitpid(child, &status, 0);
	} while (result == -1 && errno == EINTR);
	if (result != child)
		return failure(test, "waitpid", errno);
	if (WIFSIGNALED(status)) {
		printf("FAIL %s operation=child_exit signal=%d\n",
		       test, WTERMSIG(status));
		return 1;
	}
	if (!WIFEXITED(status))
		return failure(test, "unexpected_wait_status", ECHILD);
	return WEXITSTATUS(status) == 0 ? 0 : 1;
}

static int namespace_id(const char *path, char *buffer, size_t size)
{
	ssize_t length = readlink(path, buffer, size - 1);

	if (length < 0)
		return -1;
	if ((size_t)length == size - 1) {
		errno = EOVERFLOW;
		return -1;
	}
	buffer[length] = '\0';
	return 0;
}

/* Called only inside an ordinary clone child, and reaps its namespace child. */
static int namespace_probe(const char *name, const char *path,
			   unsigned long flags, probe_fn payload)
{
	char original[128];
	pid_t child;
	int failed;

	if (namespace_id(path, original, sizeof(original)))
		return failure(name, "read_original_namespace", errno);
	child = clone_process(flags);
	if (child < 0)
		return failure(name, "clone_new_namespace", errno);
	if (child == 0) {
		char isolated[128];

		if (namespace_id(path, isolated, sizeof(isolated)))
			_exit(failure(name, "read_child_namespace", errno));
		if (!strcmp(original, isolated))
			_exit(failure(name, "namespace_identity_unchanged", EPROTO));
		_exit(payload ? payload() : 0);
	}
	failed = reap(child, name);
	return failed;
}

static int pid_one(void)
{
	long result = syscall(SYS_getpid);

	if (result != 1) {
		printf("FAIL pid_namespace operation=getpid expected=1 actual=%ld errno=%d\n",
		       result, result < 0 ? errno : EPROTO);
		return 1;
	}
	return 0;
}

static int pid_namespace(void)
{
	return namespace_probe("pid_namespace", "/proc/self/ns/pid",
			       CLONE_NEWPID, pid_one);
}

static int ipc_objects(void)
{
	long id;
	int failed = 0;

	id = syscall(SYS_msgget, IPC_PRIVATE, IPC_CREAT | 0600);
	if (id < 0) {
		failed |= failure("sysvipc_msg", "msgget", errno);
	} else if (syscall(SYS_msgctl, id, IPC_RMID, 0UL) < 0) {
		failed |= failure("sysvipc_msg", "msgctl_IPC_RMID", errno);
	} else {
		puts("PASS sysvipc_msg create_remove");
	}

	id = syscall(SYS_shmget, IPC_PRIVATE, 4096UL, IPC_CREAT | 0600);
	if (id < 0) {
		failed |= failure("sysvipc_shm", "shmget", errno);
	} else if (syscall(SYS_shmctl, id, IPC_RMID, 0UL) < 0) {
		failed |= failure("sysvipc_shm", "shmctl_IPC_RMID", errno);
	} else {
		puts("PASS sysvipc_shm create_remove");
	}

	id = syscall(SYS_semget, IPC_PRIVATE, 1UL, IPC_CREAT | 0600);
	if (id < 0) {
		failed |= failure("sysvipc_sem", "semget", errno);
	} else if (syscall(SYS_semctl, id, 0UL, IPC_RMID, 0UL) < 0) {
		failed |= failure("sysvipc_sem", "semctl_IPC_RMID", errno);
	} else {
		puts("PASS sysvipc_sem create_remove");
	}
	/* All remaining objects are confined to this new IPC namespace. */
	return failed;
}

static int sysvipc_newipc(void)
{
	return namespace_probe("sysvipc_newipc", "/proc/self/ns/ipc",
			       CLONE_NEWIPC, ipc_objects);
}

static int user_namespace(void)
{
	/* No uid/gid mappings or host credential changes are performed. */
	return namespace_probe("user_namespace", "/proc/self/ns/user",
			       CLONE_NEWUSER, NULL);
}

static int net_namespace(void)
{
	return namespace_probe("net_namespace", "/proc/self/ns/net",
			       CLONE_NEWNET, NULL);
}

static int mount_namespace(void)
{
	/* Clone only: never mount/unmount or alter mount propagation. */
	return namespace_probe("mount_namespace", "/proc/self/ns/mnt",
			       CLONE_NEWNS, NULL);
}

static int seccomp_filter(void)
{
	struct sock_filter instructions[] = {
		BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
			 offsetof(struct seccomp_data, nr)),
		BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_getppid, 0, 1),
		BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
		BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
	};
	struct sock_fprog program = {
		.len = sizeof(instructions) / sizeof(instructions[0]),
		.filter = instructions,
	};
	long original_pid = syscall(SYS_getpid);
	long result;
	int error;

	result = syscall(SYS_getppid);
	if (result <= 0)
		return failure("seccomp_filter", "getppid_before_filter",
			       result < 0 ? errno : EPROTO);
	if (prctl(PR_SET_NO_NEW_PRIVS, 1UL, 0UL, 0UL, 0UL))
		return failure("seccomp_filter", "PR_SET_NO_NEW_PRIVS", errno);
	result = prctl(PR_GET_NO_NEW_PRIVS, 0UL, 0UL, 0UL, 0UL);
	if (result != 1)
		return failure("seccomp_filter", "PR_GET_NO_NEW_PRIVS",
			       result < 0 ? errno : EPROTO);
	if (syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0UL, &program))
		return failure("seccomp_filter", "SECCOMP_SET_MODE_FILTER", errno);

	errno = 0;
	result = syscall(SYS_getppid);
	error = errno;
	if (result != -1 || error != EPERM) {
		printf("FAIL seccomp_filter operation=getppid_after_filter result=%ld errno=%d expected_errno=%d\n",
		       result, error, EPERM);
		return 1;
	}
	result = syscall(SYS_getpid);
	if (result != original_pid)
		return failure("seccomp_filter", "allowed_getpid_after_filter",
			       result < 0 ? errno : EPROTO);
	/* The filter and NO_NEW_PRIVS are confined to this clone child. */
	return 0;
}

static int devtmpfs_registered(void)
{
	char buffer[16384];
	size_t used = 0;
	ssize_t length;
	int descriptor = open("/proc/filesystems", O_RDONLY | O_CLOEXEC);
	int error;
	char *match;

	if (descriptor < 0)
		return failure("devtmpfs_registered", "open_proc_filesystems", errno);
	while (used < sizeof(buffer) - 1) {
		length = read(descriptor, buffer + used, sizeof(buffer) - 1 - used);
		if (length < 0 && errno == EINTR)
			continue;
		if (length < 0) {
			error = errno;
			close(descriptor);
			return failure("devtmpfs_registered", "read_proc_filesystems", error);
		}
		if (length == 0)
			break;
		used += (size_t)length;
	}
	if (close(descriptor))
		return failure("devtmpfs_registered", "close_proc_filesystems", errno);
	if (used == sizeof(buffer) - 1)
		return failure("devtmpfs_registered", "proc_filesystems_too_large", EOVERFLOW);
	buffer[used] = '\0';
	match = strstr(buffer, "devtmpfs");
	if (!match || (match != buffer && match[-1] != '\t' && match[-1] != ' ') ||
	    (match[8] != '\n' && match[8] != '\0'))
		return failure("devtmpfs_registered", "filesystem_not_registered", ENODEV);
	return 0;
}

static int run_test(const char *name, probe_fn function)
{
	pid_t child = clone_process(0);
	int failed;

	if (child < 0)
		return failure(name, "clone_isolation_child", errno);
	if (child == 0)
		_exit(function() ? 1 : 0);
	failed = reap(child, name);
	printf("%s %s\n", failed ? "FAIL" : "PASS", name);
	return failed;
}

int main(void)
{
	const struct {
		const char *name;
		probe_fn function;
	} tests[] = {
		{ "pid_namespace", pid_namespace },
		{ "sysvipc_newipc", sysvipc_newipc },
		{ "user_namespace", user_namespace },
		{ "net_namespace", net_namespace },
		{ "mount_namespace", mount_namespace },
		{ "seccomp_filter", seccomp_filter },
		{ "devtmpfs_registered", devtmpfs_registered },
	};
	size_t index;
	int failed = 0;

	setvbuf(stdout, NULL, _IONBF, 0);
	setvbuf(stderr, NULL, _IONBF, 0);
	puts("kernel_probe aarch64 v1 isolated_syscall_smoke");
	if (geteuid() != 0)
		return failure("root_required", "geteuid", EPERM);
	for (index = 0; index < sizeof(tests) / sizeof(tests[0]); ++index)
		failed += run_test(tests[index].name, tests[index].function);
	printf("SUMMARY tests=%zu passed=%zu failed=%d\n",
	       sizeof(tests) / sizeof(tests[0]),
	       sizeof(tests) / sizeof(tests[0]) - (size_t)failed, failed);
	return failed ? 1 : 0;
}

