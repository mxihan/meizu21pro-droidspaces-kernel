#!/usr/bin/env python3
"""Read-only stock/final BTF layout audit, with transparent anonymous wrappers.

Run under WSL Python. The only output mutation is the requested JSON file.
BTF stores member offsets and sizes, not complete C alignment attributes.
https://docs.kernel.org/bpf/btf.html
"""

import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import re
import struct
import subprocess
import sys


BASE = "."
KINDS = {
    0: "VOID", 1: "INT", 2: "PTR", 3: "ARRAY", 4: "STRUCT", 5: "UNION",
    6: "ENUM", 7: "FWD", 8: "TYPEDEF", 9: "VOLATILE", 10: "CONST",
    11: "RESTRICT", 12: "FUNC", 13: "FUNC_PROTO", 14: "VAR",
    15: "DATASEC", 16: "FLOAT", 17: "DECL_TAG", 18: "TYPE_TAG", 19: "ENUM64",
}
MODIFIERS = {8, 9, 10, 11, 18}
ORIGINAL_TYPES = [
    "task_struct", "seccomp", "seccomp_filter", "seccomp_data", "action_cache",
    "cred", "mm_struct", "signal_struct", "thread_info", "thread_struct",
    "cgroup", "cgroup_subsys_state", "cgroup_namespace", "task_group", "cfs_rq",
    "sched_entity", "rq", "linux_binprm", "file", "file_operations",
]
ADDITIONAL_TYPES = [
    "net", "netns_core", "netns_ipv4", "netns_ipv6", "netns_nf", "netns_ct",
    "netns_nftables", "netns_ipvs", "ip_set_net", "net_generic", "ip_set", "ip_set_type",
    "net_device", "sk_buff", "skb_ext", "net_bridge", "sock", "socket",
    "nf_conn", "nf_nat_range", "nf_nat_range2", "nf_conn_nat",
    "inode", "super_block", "dentry", "address_space", "file_system_type",
    "super_operations", "inode_operations", "vfsmount", "mount", "fs_context",
    "path", "fs_struct", "files_struct", "fdtable", "kstat", "shmem_inode_info",
    "user_namespace", "ipc_namespace", "nsproxy", "pid_namespace", "pid",
    "ipc_ids", "kern_ipc_perm", "uts_namespace", "mnt_namespace",
    "device", "class", "kobject", "kernfs_node", "req", "completion", "file_handle",
    "autofs_sb_info", "autofs_info", "autofs_wait_queue", "autofs_packet_hdr",
    "sysv_sem", "sysv_shm", "sem_undo_list", "shmid_kernel", "sem_array",
    "msg_queue", "msg_msg", "skb_ext_id", "cgroup_subsys_id",
]


def digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read_btf(path):
    """Extract .BTF in memory from ELF64, or read a standalone BTF blob."""
    with open(path, "rb") as stream:
        head = stream.read(64)
        if head[:4] != b"\x7fELF":
            stream.seek(0)
            return stream.read(), {"container": "raw_btf"}
        if head[4] != 2:
            raise ValueError("Only ELF64 inputs are supported")
        endian = "<" if head[5] == 1 else ">"
        header = struct.unpack(endian + "HHIQQQIHHHHHH", head[16:64])
        shoff, shentsize, shnum, shstrndx = header[5], header[10], header[11], header[12]
        if shentsize < 64:
            raise ValueError("ELF section header is too short")
        stream.seek(shoff)
        section0 = struct.unpack(endian + "IIQQQQIIQQ", stream.read(64))
        if shnum == 0:
            shnum = section0[5]
        if shstrndx == 0xFFFF:
            shstrndx = section0[6]
        stream.seek(shoff + shstrndx * shentsize)
        names_header = struct.unpack(endian + "IIQQQQIIQQ", stream.read(64))
        stream.seek(names_header[4])
        names = stream.read(names_header[5])
        for index in range(shnum):
            stream.seek(shoff + index * shentsize)
            section = struct.unpack(endian + "IIQQQQIIQQ", stream.read(64))
            name = names[section[0]:].split(b"\0", 1)[0]
            if name == b".BTF":
                if section[2] & 0x800:
                    raise ValueError("Compressed ELF .BTF is not supported")
                stream.seek(section[4])
                return stream.read(section[5]), {
                    "container": "ELF64", "elf_machine": header[1],
                    "btf_section_file_offset": section[4],
                    "btf_section_size_bytes": section[5],
                    "btf_section_alignment_bytes": section[8],
                }
    raise ValueError("ELF has no .BTF section")


class BTF:
    def __init__(self, path):
        self.path = str(path)
        self.raw, self.container = read_btf(path)
        self.endian = "<" if self.raw[:2] == b"\x9f\xeb" else ">"
        header = struct.unpack_from(self.endian + "HBBIIIII", self.raw)
        magic, version, flags, hdr_len, type_off, type_len, str_off, str_len = header
        if magic != 0xEB9F or version != 1:
            raise ValueError("Not supported BTF v1")
        if hdr_len < 24 or hdr_len + max(type_off + type_len, str_off + str_len) > len(self.raw):
            raise ValueError("Invalid BTF section bounds")
        self.header = {"version": version, "flags": flags, "header_length": hdr_len,
                       "type_length": type_len, "string_length": str_len,
                       "endianness": "little" if self.endian == "<" else "big"}
        self.strings = self.raw[hdr_len + str_off:hdr_len + str_off + str_len]
        self.types = [{"id": 0, "name": "void", "kind": 0, "size_type": 0}]
        self.names = collections.defaultdict(list)
        pos, end = hdr_len + type_off, hdr_len + type_off + type_len
        while pos < end:
            name_off, info, size_type = struct.unpack_from(self.endian + "III", self.raw, pos)
            pos += 12
            kind, vlen, kflag = (info >> 24) & 0x1F, info & 0xFFFF, bool(info >> 31)
            item = {"id": len(self.types), "name": self.string(name_off), "kind": kind,
                    "vlen": vlen, "kflag": kflag, "size_type": size_type}
            if kind == 1:
                item["encoding"] = struct.unpack_from(self.endian + "I", self.raw, pos)[0]
                pos += 4
            elif kind == 3:
                item["element"], item["index"], item["count"] = struct.unpack_from(
                    self.endian + "III", self.raw, pos)
                pos += 12
            elif kind in (4, 5):
                item["members"] = []
                for _ in range(vlen):
                    member_name, member_type, encoded = struct.unpack_from(
                        self.endian + "III", self.raw, pos)
                    pos += 12
                    item["members"].append({
                        "name": self.string(member_name), "type_id": member_type,
                        "offset_bits": encoded & 0xFFFFFF if kflag else encoded,
                        "bitfield_size_bits": encoded >> 24 if kflag else 0,
                    })
            elif kind in (6, 19):
                item["values"] = []
                for _ in range(vlen):
                    if kind == 6:
                        enum_name, value = struct.unpack_from(self.endian + "II", self.raw, pos)
                        pos += 8
                        if kflag and value >= 1 << 31:
                            value -= 1 << 32
                    else:
                        enum_name, low, high = struct.unpack_from(self.endian + "III", self.raw, pos)
                        pos += 12
                        value = (high << 32) | low
                        if kflag and value >= 1 << 63:
                            value -= 1 << 64
                    item["values"].append({"name": self.string(enum_name), "value": value})
            elif kind == 13:
                item["params"] = []
                for _ in range(vlen):
                    param_name, param_type = struct.unpack_from(self.endian + "II", self.raw, pos)
                    pos += 8
                    item["params"].append({"name": self.string(param_name), "type_id": param_type})
            elif kind in (14, 17):
                item["extra"] = struct.unpack_from(self.endian + "I", self.raw, pos)[0]
                pos += 4
            elif kind == 15:
                pos += vlen * 12
            elif kind not in (0, 2, 7, 8, 9, 10, 11, 12, 16, 18):
                raise ValueError("Unsupported BTF kind %s" % kind)
            if pos > end:
                raise ValueError("BTF record exceeds type section")
            self.types.append(item)
            if item["name"]:
                self.names[item["name"]].append(item["id"])
        if pos != end:
            raise ValueError("BTF type stream did not end exactly")
        self._size_cache = {}

    def string(self, offset):
        if offset >= len(self.strings):
            raise ValueError("BTF string offset outside string section")
        end = self.strings.find(b"\0", offset)
        if end < 0:
            raise ValueError("BTF string is not terminated")
        return self.strings[offset:end].decode("utf-8", "replace")

    def resolve(self, type_id):
        visited = set()
        while self.types[type_id]["kind"] in MODIFIERS:
            if type_id in visited:
                raise ValueError("Cyclic BTF modifier chain")
            visited.add(type_id)
            type_id = self.types[type_id]["size_type"]
        return type_id

    def size(self, type_id):
        type_id = self.resolve(type_id)
        if type_id in self._size_cache:
            return self._size_cache[type_id]
        item = self.types[type_id]
        kind = item["kind"]
        if kind in (1, 4, 5, 6, 16, 19):
            value = item["size_type"]
        elif kind == 2:
            value = 8
        elif kind == 3:
            value = self.size(item["element"]) * item["count"]
        else:
            value = 0
        self._size_cache[type_id] = value
        return value

    def describe(self, type_id, seen=()):
        type_id = self.resolve(type_id)
        item = self.types[type_id]
        kind = item["kind"]
        result = {"kind": KINDS[kind], "name": item["name"], "storage_size_bytes": self.size(type_id)}
        if type_id in seen:
            result["recursion_terminal"] = True
        elif kind == 1:
            encoding = item["encoding"]
            result.update({"integer_encoding": (encoding >> 24) & 0xF,
                           "integer_offset_bits": (encoding >> 16) & 0xFF,
                           "integer_width_bits": encoding & 0xFF})
        elif kind == 2:
            pointee_id = self.resolve(item["size_type"])
            pointee = self.types[pointee_id]
            if pointee["kind"] in (0, 4, 5, 7):
                result["pointee"] = {"kind": KINDS[pointee["kind"]], "name": pointee["name"]}
            else:
                result["pointee"] = self.describe(pointee_id, seen + (type_id,))
        elif kind == 3:
            result.update({"element_count": item["count"], "element_stride_bytes": self.size(item["element"]),
                           "element_type": self.describe(item["element"], seen + (type_id,))})
        elif kind in (6, 19):
            result.update({"signed": item["kflag"], "enum_values": item["values"]})
        elif kind == 13:
            result["return_type"] = self.describe(item["size_type"], seen + (type_id,))
            result["parameters"] = [self.describe(p["type_id"], seen + (type_id,)) for p in item["params"]]
        return result

    def fields(self, type_id):
        """Flatten all named by-value members, eliding anonymous wrappers.

        Arrays keep their length/stride in the parent entry and recursively
        compare one representative element at [*]. Pointers are not chased.
        """
        result = []
        wrapper_count = 0

        def walk(current_id, prefix, base_bits, ancestry):
            nonlocal wrapper_count
            current_id = self.resolve(current_id)
            if current_id in ancestry:
                raise ValueError("Illegal recursive by-value aggregate")
            item = self.types[current_id]
            if item["kind"] == 3:
                walk(item["element"], prefix + "[*]", base_bits, ancestry + (current_id,))
                return
            if item["kind"] not in (4, 5):
                return
            for member in item["members"]:
                member_id = self.resolve(member["type_id"])
                member_type = self.types[member_id]
                offset = base_bits + member["offset_bits"]
                if not member["name"]:
                    wrapper_count += 1
                    walk(member_id, prefix, offset, ancestry + (current_id,))
                    continue
                path = prefix + ("." if prefix else "") + member["name"]
                width = member["bitfield_size_bits"]
                # Older BTF may encode bit widths on the INT rather than member.
                if not width and member_type["kind"] == 1:
                    encoding = member_type["encoding"]
                    encoded_width = encoding & 0xFF
                    if encoded_width != self.size(member_id) * 8:
                        width = encoded_width
                        offset += (encoding >> 16) & 0xFF
                result.append({
                    "path": path, "absolute_offset_bits": offset,
                    "absolute_offset_bytes": offset // 8 if offset % 8 == 0 else None,
                    "storage_size_bytes": self.size(member_id),
                    "bitfield_width_bits": width,
                    "type": self.describe(member_id),
                })
                walk(member_id, path, offset, ancestry + (current_id,))

        walk(type_id, "", 0, ())
        result.sort(key=lambda field: (field["path"], field["absolute_offset_bits"], digest(field)))
        return result, wrapper_count

    def candidates(self, name):
        ids = [type_id for type_id in self.names.get(name, [])
               if self.types[type_id]["kind"] in (4, 5, 6, 19)]
        return ids

    def select(self, name):
        ids = self.candidates(name)
        variants = collections.defaultdict(list)
        for type_id in ids:
            fields, _ = self.fields(type_id)
            key = digest({"type": self.describe(type_id), "fields": fields})
            variants[key].append(type_id)
        return (ids[0] if ids else None), {"type_ids": ids, "distinct_layout_count": len(variants),
                                         "layout_variant_type_ids": list(variants.values())}


def pahole_alignment(path, name):
    process = subprocess.run(["pahole", "-F", "btf", "-C", name, path],
                             capture_output=True, text=True, check=False)
    if process.returncode or not process.stdout.strip():
        return {"status": "unavailable", "exit_code": process.returncode,
                "error": process.stderr.strip()[:1000]}
    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    terminator = lines[-1] if lines else ""
    matched = re.search(r"__aligned__\((\d+)\)", terminator)
    sizes = re.findall(r"/\*\s+size:\s*(\d+)", process.stdout)
    return {"status": "rendered", "encoded_alignment_bytes": None,
            "pahole_reported_size_bytes": int(sizes[-1]) if sizes else None,
            "pahole_rendered_aligned_attribute_bytes": int(matched[1]) if matched else None,
            "pahole_rendered_packed_attribute": "__packed__" in terminator,
            "pahole_type_terminator": terminator,
            "interpretation": "BTF does not encode complete C alignment; pahole attributes are reconstruction, not independent alignment proof."}


def field_groups(fields):
    result = collections.defaultdict(list)
    for field in fields:
        result[field["path"]].append(field)
    return result


def allowed_task_addition(field):
    path, bit_offset = field["path"], field["absolute_offset_bits"]
    if path == "sysvsem" or path.startswith("sysvsem."):
        return 3640 * 8 <= bit_offset and bit_offset + field["storage_size_bytes"] * 8 <= 3648 * 8
    if path == "sysvshm" or path.startswith("sysvshm."):
        return 3648 * 8 <= bit_offset and bit_offset + field["storage_size_bytes"] * 8 <= 3664 * 8
    return False


def compare_type(stock, final, name):
    stock_id, stock_selection = stock.select(name)
    final_id, final_selection = final.select(name)
    result = {"type": name, "stock_selection": stock_selection, "final_selection": final_selection,
              "member_diff": {"removed": [], "changed": [], "added": []}}
    if stock_id is None or final_id is None:
        result.update({"status": "not_present", "stock_present": stock_id is not None,
                       "final_present": final_id is not None, "compared": False,
                       "interpretation": "Not a passing comparison; absent BTF may mean configuration disabled, dead-code elimination, or unrepresented local type."})
        present_db, present_id = (final, final_id) if final_id is not None else (stock, stock_id)
        if present_id is not None:
            result["present_type_size_bytes"] = present_db.size(present_id)
            fields, wrappers = present_db.fields(present_id)
            result["present_type_evidence"] = {
                "type_id": present_id, "recursive_named_field_count": len(fields),
                "recursive_named_fields_sha256": digest(fields),
                "anonymous_wrapper_count": wrappers,
                "alignment": pahole_alignment(present_db.path, name),
            }
        return result
    stock_fields, stock_wrappers = stock.fields(stock_id)
    final_fields, final_wrappers = final.fields(final_id)
    result.update({
        "compared": True,
        "kind": KINDS[stock.types[stock_id]["kind"]],
        "stock_size_bytes": stock.size(stock_id), "final_size_bytes": final.size(final_id),
        "size_equal": stock.size(stock_id) == final.size(final_id),
        "stock_alignment": pahole_alignment(stock.path, name),
        "final_alignment": pahole_alignment(final.path, name),
        "stock_recursive_named_field_count": len(stock_fields),
        "final_recursive_named_field_count": len(final_fields),
        "stock_anonymous_wrapper_count": stock_wrappers, "final_anonymous_wrapper_count": final_wrappers,
        "stock_recursive_fields_sha256": digest(stock_fields),
        "final_recursive_fields_sha256": digest(final_fields),
        "stock_top_type": stock.describe(stock_id), "final_top_type": final.describe(final_id),
    })
    left, right = field_groups(stock_fields), field_groups(final_fields)
    unchanged_count = 0
    for path in sorted(left.keys() | right.keys()):
        if path not in right:
            result["member_diff"]["removed"].extend(left[path])
        elif path not in left:
            result["member_diff"]["added"].extend(right[path])
        elif left[path] != right[path]:
            result["member_diff"]["changed"].append({"path": path, "stock": left[path], "final": right[path]})
        else:
            unchanged_count += len(left[path])
    result["unchanged_original_recursive_named_field_count"] = unchanged_count
    result["original_fields_all_preserved"] = not (
        result["member_diff"]["removed"] or result["member_diff"]["changed"])
    allowed = [field for field in result["member_diff"]["added"] if name == "task_struct" and allowed_task_addition(field)]
    unexpected = [field for field in result["member_diff"]["added"] if field not in allowed]
    result["allowed_additions"] = allowed
    result["unexpected_additions"] = unexpected
    result["enum_values_equal"] = stock.types[stock_id].get("values") == final.types[final_id].get("values")
    result["pahole_size_crosscheck"] = {
        label: evidence.get("pahole_reported_size_bytes") == db.size(type_id)
        if db.types[type_id]["kind"] in (4, 5) else None
        for label, evidence, db, type_id in (
            ("stock", result["stock_alignment"], stock, stock_id),
            ("final", result["final_alignment"], final, final_id))
    }
    align_keys = ("pahole_rendered_aligned_attribute_bytes", "pahole_rendered_packed_attribute")
    result["pahole_alignment_reconstruction_equal"] = all(
        result["stock_alignment"].get(key) == result["final_alignment"].get(key) for key in align_keys)
    ambiguous = stock_selection["distinct_layout_count"] != 1 or final_selection["distinct_layout_count"] != 1
    if ambiguous:
        result["status"] = "ambiguous_type_name_requires_review"
    elif (result["size_equal"] and result["original_fields_all_preserved"] and not unexpected
          and result["enum_values_equal"] and result["pahole_alignment_reconstruction_equal"]
          and all(value is not False for value in result["pahole_size_crosscheck"].values())):
        result["status"] = "compatible_with_reserved_slot_additions" if allowed else "equal"
    else:
        result["status"] = "differences_require_review"
    if name == "task_struct":
        result["stock_all_recursive_fields"] = stock_fields
        result["final_all_recursive_fields"] = final_fields
    return result


def parse_config(path):
    result = {}
    for line in pathlib.Path(path).read_text().splitlines():
        match = re.match(r"^(CONFIG_[A-Z0-9_]+)=(.*)$", line)
        disabled = re.match(r"^# (CONFIG_[A-Z0-9_]+) is not set$", line)
        if match:
            result[match[1]] = match[2]
        elif disabled:
            result[disabled[1]] = "n"
    return result


def assess_not_present(result, configs):
    """Record source/config interpretation without converting absence to pass."""
    name = result["type"]
    families = {
        "netns_nftables": ("CONFIG_NF_TABLES", "NF_TABLES is disabled in both builds; its conditional struct net field remains absent."),
        "netns_ipvs": ("CONFIG_IP_VS", "IP_VS is disabled in both builds; only a forward declaration may survive in BTF."),
        "ip_set_net": ("CONFIG_IP_SET", "New IP_SET private per-netns object, allocated by register_pernet_subsys via net_generic; it is not embedded in struct net."),
        "ip_set": ("CONFIG_IP_SET", "New IP_SET subsystem type; no stock layout exists to compare."),
        "ip_set_type": ("CONFIG_IP_SET", "New IP_SET subsystem type; no stock layout exists to compare."),
        "autofs_sb_info": ("CONFIG_AUTOFS_FS", "New autofs private superblock state; no stock layout exists to compare."),
        "autofs_info": ("CONFIG_AUTOFS_FS", "New autofs private inode state; no stock layout exists to compare."),
        "autofs_wait_queue": ("CONFIG_AUTOFS_FS", "New autofs wait-queue state; no stock layout exists to compare."),
        "autofs_packet_hdr": ("CONFIG_AUTOFS_FS", "New autofs userspace protocol header; no stock layout exists to compare."),
        "req": ("CONFIG_DEVTMPFS", "New drivers/base/devtmpfs.c private struct req; selected shared device/VFS/locking types are compared separately."),
        "file_handle": ("CONFIG_FHANDLE", "FHANDLE syscall data type; no stock complete layout exists in the captured BTF to compare."),
    }
    for ipc_type in ("sysv_sem", "sysv_shm", "sem_undo_list", "shmid_kernel", "sem_array", "msg_queue", "msg_msg"):
        families[ipc_type] = ("CONFIG_SYSVIPC", "New SYSVIPC type. Shared ipc_namespace and original task_struct fields are compared separately; new sysvsem/sysvshm placement has explicit slot assertions.")
    if name in families:
        config, assessment = families[name]
        result["manual_source_assessment"] = {
            "controlling_config": config,
            "stock_config": configs["stock"].get(config),
            "final_config": configs["final"].get(config),
            "assessment": assessment,
            "comparison_still_not_performed": True,
        }
    else:
        result["manual_source_assessment"] = {
            "assessment": "Unclassified missing type requires separate human review; no pass is inferred.",
            "comparison_still_not_performed": True,
        }


def slot_checks(stock, final):
    stock_id, _ = stock.select("task_struct")
    final_id, _ = final.select("task_struct")
    if stock_id is None or final_id is None:
        return {"status": "not_present", "passed": False}
    left = field_groups(stock.fields(stock_id)[0])
    right = field_groups(final.fields(final_id)[0])
    wanted = {"android_kabi_reserved6": (3640, 8), "android_kabi_reserved7": (3648, 8),
              "android_kabi_reserved8": (3656, 8), "thread": (3664, 1120)}
    checks = []
    for path, (offset, size) in wanted.items():
        observed = {label: fields.get(path, []) for label, fields in (("stock", left), ("final", right))}
        okay = all(len(fields) == 1 and fields[0]["absolute_offset_bits"] == offset * 8
                   and fields[0]["storage_size_bytes"] == size for fields in observed.values())
        checks.append({"field": path, "expected_offset_bytes": offset, "expected_size_bytes": size,
                       "observed": observed, "passed": okay})
    for path, offset, size in (("sysvsem", 3640, 8), ("sysvshm", 3648, 16)):
        values = right.get(path, [])
        checks.append({"field": path, "expected_offset_bytes": offset, "expected_size_bytes": size,
                       "stock_present": path in left, "final": values,
                       "passed": path not in left and len(values) == 1
                       and values[0]["absolute_offset_bits"] == offset * 8
                       and values[0]["storage_size_bytes"] == size})
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", default=BASE + "/output/droidspaces-20261019/device-baseline-v1/vmlinux.btf")
    parser.add_argument("--final", default="vmlinux")
    parser.add_argument("--stock-config", default=BASE + "/output/droidspaces-20261019/device-baseline-v1/stock.config")
    parser.add_argument("--final-config", default=".config")
    parser.add_argument("--output", default=BASE + "/output/droidspaces-20261019/verification/final-btf-layouts.json")
    args = parser.parse_args()
    stock, final = BTF(args.stock), BTF(args.final)
    configurations = {"stock": parse_config(args.stock_config), "final": parse_config(args.final_config)}
    watched = ["CONFIG_RANDSTRUCT_NONE", "CONFIG_RANDSTRUCT_FULL", "CONFIG_RANDSTRUCT_PERFORMANCE",
               "CONFIG_RANDOMIZE_BASE", "CONFIG_RANDOMIZE_KSTACK_OFFSET", "CONFIG_SYSVIPC",
               "CONFIG_IP_SET", "CONFIG_IP6_NF_NAT", "CONFIG_FHANDLE", "CONFIG_AUTOFS_FS",
               "CONFIG_DEVTMPFS", "CONFIG_CFS_BANDWIDTH", "CONFIG_CGROUP_PIDS",
               "CONFIG_CGROUP_DEVICE", "CONFIG_NF_TABLES", "CONFIG_IP_VS", "CONFIG_BRIDGE_NETFILTER"]
    config_evidence = {label: {key: config.get(key) for key in watched} for label, config in configurations.items()}
    randomization_off = all(config.get("CONFIG_RANDSTRUCT_NONE") == "y"
                            and config.get("CONFIG_RANDSTRUCT_FULL") != "y"
                            and config.get("CONFIG_RANDSTRUCT_PERFORMANCE") != "y"
                            for config in configurations.values())
    results = [compare_type(stock, final, name) for name in dict.fromkeys(ORIGINAL_TYPES + ADDITIONAL_TYPES)]
    for result in results:
        if result["status"] == "not_present":
            assess_not_present(result, configurations)
    summary = dict(collections.Counter(result["status"] for result in results))
    failures = [result["type"] for result in results if result["status"] in
                ("differences_require_review", "ambiguous_type_name_requires_review")]
    task = next(result for result in results if result["type"] == "task_struct")
    slots = slot_checks(stock, final)
    source_meta = {}
    for label, db, config_path in (("stock", stock, args.stock_config), ("final", final, args.final_config)):
        source_meta[label] = {"path": db.path, "file_size_bytes": pathlib.Path(db.path).stat().st_size,
                              "file_sha256": file_sha256(db.path), "btf_sha256": hashlib.sha256(db.raw).hexdigest(),
                              "btf_type_count": len(db.types) - 1, "btf_header": db.header,
                              "container": db.container, "config_path": config_path,
                              "config_sha256": file_sha256(config_path)}
    output = {
        "schema_version": 1,
        "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "script_sha256": file_sha256(__file__),
        "method": "Parse raw BTF or ELF .BTF; erase typedef/qualifier wrappers; recursively compare named by-value member paths, absolute bit offsets, storage sizes, bit widths and type signatures. Promote anonymous struct/union members without changing offsets. Compare array element layout with length and stride. Cross-check alignment reconstruction with pahole.",
        "pointer_size_bytes": 8,
        "pahole_version": subprocess.check_output(["pahole", "--version"], text=True).strip(),
        "inputs": source_meta,
        "configuration_evidence": config_evidence,
        "structure_randomization_disabled": randomization_off,
        "task_struct_sysvipc_reserved_slot_checks": slots,
        "summary": {
            "requested_type_count": len(results), "status_counts": summary,
            "compared_type_count": sum(result["compared"] for result in results),
            "not_present_type_count": sum(not result["compared"] for result in results),
            "types_requiring_difference_review": failures,
            "original_twenty_types_all_compared_and_compatible": all(
                result["status"] in ("equal", "compatible_with_reserved_slot_additions")
                for result in results if result["type"] in ORIGINAL_TYPES),
            "task_struct_all_original_recursive_named_fields_preserved": task.get("original_fields_all_preserved", False),
            "physical_layout_checks_passed_for_compared_unambiguous_types": not failures and slots["passed"] and randomization_off,
            "complete_kernel_abi_compatibility_proven": False,
        },
        "boundaries": [
            "Not-present types are NOT passes; per-type presence is explicit and requires configuration/source interpretation.",
            "BTF v1 stores sizes/member bit offsets, not complete aggregate/member C alignment or packing attributes; pahole alignment is reconstruction. Equal reconstruction is not proof of identical C _Alignof.",
            "Recursive traversal follows embedded aggregates and one representative array element, with array count/stride verified. It stops at pointer targets; named pointer-target types in the requested list are independently compared.",
            "Qualifiers, typedef aliases and BTF IDs are erased for physical comparison. Function pointer signatures retain terminal type identities but do not recursively inspect pointee object layouts.",
            "All original named fields, including promoted anonymous members and preserved KABI reserve fields, must retain exact absolute bit offset, byte storage size, bitfield width and normalized type signature.",
            "Only task_struct additions rooted at sysvsem within bytes 3640..3647 and sysvshm within 3648..3663 are automatically accepted. Anonymous packaging differences themselves are not layout changes.",
            "This selected-type BTF audit does not replace module CRC/Module.symvers analysis, enum semantics outside represented types, exported symbol/function ABI, load-signature checks, runtime testing, or full vendor module verification.",
            "RANDSTRUCT_NONE is checked separately from enabled address/KASLR or kernel-stack offset randomization; address randomization does not mean structure field randomization.",
        ],
        "types": results,
    }
    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps({"output": str(output_path), "sha256": file_sha256(output_path),
                      "summary": output["summary"], "task_slot_checks_passed": slots["passed"]},
                     ensure_ascii=False, allow_nan=False))
    return 0 if not failures and slots["passed"] and randomization_off else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"fatal_error": str(error), "error_type": type(error).__name__}, allow_nan=False))
        raise


