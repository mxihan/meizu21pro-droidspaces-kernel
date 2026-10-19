#!/usr/bin/env python3
"""Read-only ARM64 module CRC audit against a completed kernel build.

Requires pyelftools. Inputs are never changed. Only --report is written.
Every __versions record is checked against the target core or an actual
export of another supplied module. An unreadable record/export is an error.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection


EXPORT_SECTION = re.compile(
    r"^__ksymtab(?:_gpl|_unused|_unused_gpl|_gpl_future)?$|^___ksymtab[^+]*\+.+$"
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def crc_hex(crc: int | None) -> str | None:
    return None if crc is None else f"0x{crc:08x}"


def stable_read(path: Path) -> bytes:
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"input changed while reading: {path}")
    if len(data) != after.st_size:
        raise ValueError(f"short read: {path}")
    return data


def read_core(path: Path) -> tuple[dict, dict]:
    data = stable_read(path)
    symbols = {}
    for lineno, line in enumerate(data.decode("utf-8").splitlines(), 1):
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 4:
            raise ValueError(f"{path}:{lineno}: incomplete symvers entry")
        crc = int(fields[0], 16)
        if crc > 0xFFFFFFFF or fields[2] != "vmlinux":
            raise ValueError(f"{path}:{lineno}: not a core-only 32-bit CRC entry")
        record = {
            "crc": crc_hex(crc), "export_type": fields[3],
            "namespace": fields[4] if len(fields) > 4 else "", "line": lineno,
        }
        if fields[1] in symbols:
            raise ValueError(f"{path}:{lineno}: duplicate core export {fields[1]}")
        symbols[fields[1]] = record
    if not symbols:
        raise ValueError(f"empty core symvers: {path}")
    return symbols, {"path": str(path), "sha256": digest(data), "exports": len(symbols)}


def expected_vermagic(symvers: Path, explicit: str | None) -> tuple[str, dict]:
    build = symvers.parent
    release_path = build / "include/config/kernel.release"
    config_path = build / ".config"
    evidence = {}
    release = None
    if release_path.is_file():
        data = stable_read(release_path)
        release = data.decode().strip()
        evidence["kernel_release"] = {
            "path": str(release_path), "sha256": digest(data), "value": release,
        }
    if explicit:
        value = " ".join(explicit.split())
        if release and value.split()[0] != release:
            raise ValueError("--expected-vermagic release differs from target kernel.release")
        evidence["method"] = "explicit full vermagic, cross-checked with target release if present"
        return value, evidence
    if not release or not config_path.is_file():
        raise ValueError("target .config/kernel.release missing; supply --expected-vermagic")
    data = stable_read(config_path)
    config = dict(
        line.split("=", 1) for line in data.decode().splitlines()
        if line.startswith("CONFIG_") and "=" in line
    )
    if config.get("CONFIG_ARM64") != "y":
        raise ValueError("automatic vermagic supports CONFIG_ARM64=y only")
    if config.get("CONFIG_RANDSTRUCT") == "y":
        raise ValueError("RANDSTRUCT hash requires explicit --expected-vermagic")
    tokens = [release]
    for option, token in [("CONFIG_SMP", "SMP")]:
        if config.get(option) == "y":
            tokens.append(token)
    if config.get("CONFIG_PREEMPT_RT") == "y":
        tokens.append("preempt_rt")
    elif config.get("CONFIG_PREEMPT_BUILD") == "y" or config.get("CONFIG_PREEMPT") == "y":
        tokens.append("preempt")
    for option, token in [
        ("CONFIG_MODULE_UNLOAD", "mod_unload"), ("CONFIG_MODVERSIONS", "modversions"),
    ]:
        if config.get(option) == "y":
            tokens.append(token)
    tokens.append("aarch64")
    evidence["config"] = {"path": str(config_path), "sha256": digest(data)}
    evidence["method"] = "target kernel.release plus ARM64 vermagic options from target .config"
    return " ".join(tokens), evidence


def parse_module(path: Path, data: bytes) -> dict:
    import io

    record = {
        "file_name": path.name, "sha256": digest(data), "size": len(data),
        "paths": [str(path)], "parse_errors": [], "exports": {}, "versions": {},
    }
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 64 or not elf.little_endian or elf["e_machine"] != "EM_AARCH64":
        raise ValueError("requires little-endian ELF64 AArch64 module")
    if elf["e_type"] != "ET_REL":
        raise ValueError("module ELF type is not ET_REL")
    sections = list(elf.iter_sections())
    symtab = elf.get_section_by_name(".symtab")
    if symtab is None:
        raise ValueError("module has no .symtab; exports cannot be verified")
    symbols = list(symtab.iter_symbols())
    info = elf.get_section_by_name(".modinfo")
    if info is None:
        raise ValueError("module has no .modinfo")
    modinfo = defaultdict(list)
    for item in info.data().split(b"\0"):
        if item:
            key, value = item.decode("utf-8", errors="strict").split("=", 1)
            modinfo[key].append(value)
    record["modinfo"] = dict(modinfo)
    for key in ["name", "vermagic"]:
        if len(modinfo[key]) != 1 or not modinfo[key][0]:
            raise ValueError(f"module must have exactly one nonempty {key}")
    record["module_name"] = modinfo["name"][0]
    record["vermagic"] = " ".join(modinfo["vermagic"][0].split())
    versions = elf.get_section_by_name("__versions")
    if versions is None or not versions["sh_size"]:
        raise ValueError("missing/empty __versions in modversions audit")
    raw = versions.data()
    if len(raw) % 64:
        raise ValueError("__versions length is not a multiple of 64 bytes")
    for offset in range(0, len(raw), 64):
        crc = struct.unpack_from("<Q", raw, offset)[0]
        name_bytes = raw[offset + 8:offset + 64]
        if b"\0" not in name_bytes:
            raise ValueError(f"unterminated __versions name at {offset}")
        name = name_bytes.split(b"\0", 1)[0].decode("ascii", errors="strict")
        if not name or crc > 0xFFFFFFFF or name in record["versions"]:
            raise ValueError(f"invalid/duplicate __versions record at {offset}: {name}")
        record["versions"][name] = crc_hex(crc)
    undefined = {
        s.name: s["st_info"]["bind"] for s in symbols
        if s.name and s["st_shndx"] == "SHN_UNDEF"
        and s["st_info"]["bind"] in ("STB_GLOBAL", "STB_WEAK")
    }
    record["undefined_symbols"] = undefined
    record["unversioned_strong_imports"] = sorted(
        name for name, binding in undefined.items()
        if binding == "STB_GLOBAL" and name not in record["versions"]
    )
    record["unversioned_weak_imports"] = sorted(
        name for name, binding in undefined.items()
        if binding == "STB_WEAK" and name not in record["versions"]
    )
    relocations = defaultdict(list)
    relevant_sections = {
        index for index, section in enumerate(sections)
        if EXPORT_SECTION.match(section.name) or "kcrctab" in section.name
    }
    for sec in sections:
        if isinstance(sec, RelocationSection) and sec["sh_info"] in relevant_sections:
            relsymtab = elf.get_section(sec["sh_link"])
            for rel in sec.iter_relocations():
                relocations[(sec["sh_info"], rel["r_offset"])].append(
                    (rel, relsymtab.get_symbol(rel["r_info_sym"]))
                )

    def target_string(sec_index: int, offset: int) -> str:
        rels = relocations.get((sec_index, offset), [])
        if len(rels) != 1:
            raise ValueError(f"expected one name/namespace relocation at {sec_index}:{offset}")
        rel, target = rels[0]
        if not isinstance(target["st_shndx"], int) or not rel.is_RELA():
            raise ValueError("unsupported symbol-string relocation")
        start = target["st_value"] + rel["r_addend"]
        content = elf.get_section(target["st_shndx"]).data()
        if start < 0 or start >= len(content) or b"\0" not in content[start:]:
            raise ValueError("export name/namespace pointer is outside its string table")
        return content[start:].split(b"\0", 1)[0].decode("ascii", errors="strict")

    def crc_at(sec_index: int, offset: int) -> int:
        sec = elf.get_section(sec_index)
        if "kcrctab" not in sec.name or offset < 0 or offset + 4 > sec["sh_size"]:
            raise ValueError("CRC pointer does not refer to a complete kcrctab entry")
        rels = relocations.get((sec_index, offset), [])
        if not rels:
            return struct.unpack_from("<I", sec.data(), offset)[0]
        if len(rels) != 1:
            raise ValueError("multiple relocations on one CRC entry")
        rel, target = rels[0]
        if not rel.is_RELA() or not target.name.startswith("__crc_"):
            raise ValueError("unsupported CRC relocation; CRC left unresolved")
        if target["st_shndx"] == "SHN_ABS":
            return (target["st_value"] + rel["r_addend"]) & 0xFFFFFFFF
        if isinstance(target["st_shndx"], int):
            return crc_at(target["st_shndx"], target["st_value"] + rel["r_addend"])
        raise ValueError("CRC relocation has no resolved __crc_* target")

    crc_symbols = defaultdict(list)
    for symbol in symbols:
        if symbol.name.startswith("__crc_"):
            crc_symbols[symbol.name[6:]].append(symbol)
    for sec_index, sec in enumerate(sections):
        if not EXPORT_SECTION.match(sec.name):
            continue
        entries = sorted(
            (s for s in symbols if s["st_shndx"] == sec_index
             and s.name.startswith("__ksymtab_")), key=lambda s: s["st_value"]
        )
        if not entries:
            if sec["sh_size"]:
                record["parse_errors"].append(f"{sec.name}: no __ksymtab_* labels")
            continue
        stride = sec["sh_size"] // len(entries)
        if stride not in (12, 24) or stride * len(entries) != sec["sh_size"]:
            record["parse_errors"].append(f"{sec.name}: unsupported export entry size/count")
            continue
        word_size = stride // 3
        crc_section = elf.get_section_by_name(sec.name.replace("ksymtab", "kcrctab", 1))
        for ordinal, symbol in enumerate(entries):
            name = symbol.name[len("__ksymtab_"):]
            export = {"crc": None, "namespace": None, "export_type": (
                "EXPORT_SYMBOL_GPL" if "gpl" in sec.name else "EXPORT_SYMBOL"
            ), "section": sec.name, "offset": symbol["st_value"]}
            try:
                offset = symbol["st_value"]
                if offset != ordinal * stride:
                    raise ValueError("export labels do not cover every table entry in order")
                encoded_name = target_string(sec_index, offset + word_size)
                if encoded_name != name:
                    raise ValueError(f"export name relocation differs: {encoded_name}")
                export["namespace"] = target_string(sec_index, offset + 2 * word_size)
                crc_candidates = crc_symbols.get(name, [])
                if len(crc_candidates) > 1:
                    raise ValueError("multiple __crc_* symbols for export")
                if crc_candidates:
                    crc_symbol = crc_candidates[0]
                    index = crc_symbol["st_shndx"]
                    if index == "SHN_ABS":
                        crc = crc_symbol["st_value"] & 0xFFFFFFFF
                        export["crc_source"] = "absolute __crc_* symbol"
                    elif isinstance(index, int):
                        crc = crc_at(index, crc_symbol["st_value"])
                        export["crc_source"] = "__crc_* label in __kcrctab"
                    else:
                        raise ValueError("unresolved __crc_* symbol")
                elif crc_section is not None:
                    index = next(i for i, section in enumerate(sections)
                                 if section.name == crc_section.name)
                    crc = crc_at(index, ordinal * 4)
                    export["crc_source"] = "corresponding ordered __kcrctab entry"
                else:
                    raise ValueError("export has no readable CRC")
                export["crc"] = crc_hex(crc)
                if crc_section is not None:
                    index = next(i for i, section in enumerate(sections)
                                 if section.name == crc_section.name)
                    if crc_at(index, ordinal * 4) != crc:
                        raise ValueError("__crc_* disagrees with ordered kcrctab entry")
                if name in record["exports"]:
                    raise ValueError("duplicate exported symbol in one module")
            except Exception as exc:
                record["parse_errors"].append(f"export {name}: {type(exc).__name__}: {exc}")
            record["exports"][name] = export
        if crc_section is not None and crc_section["sh_size"] != len(entries) * 4:
            record["parse_errors"].append(f"{crc_section.name}: export/CRC table sizes differ")
    return record


def audit(args: argparse.Namespace) -> dict:
    symvers = args.symvers.resolve(strict=True)
    core, core_meta = read_core(symvers)
    expected, evidence = expected_vermagic(symvers, args.expected_vermagic)
    report = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "scope": "Symbol CRCs, import/export resolution, full vermagic and duplicate file identity; does not prove boot, CFI type IDs, structure layout, signature trust or load order.",
        "core": core_meta, "expected_vermagic": expected,
        "target_vermagic_evidence": evidence, "module_roots": [],
        "errors": [], "modules": [], "duplicate_names": [],
    }
    by_content = {}
    by_filename = defaultdict(list)
    seen_paths = set()
    for root_arg in args.modules:
        root = root_arg.resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"module root is not a directory: {root}")
        paths = sorted(root.rglob("*.ko"))
        report["module_roots"].append({"path": str(root), "file_count": len(paths)})
        if not paths:
            report["errors"].append({"kind": "empty_root", "path": str(root)})
        for path in paths:
            path = path.resolve(strict=True)
            if path in seen_paths:
                report["errors"].append({"kind": "overlapping_input_roots", "path": str(path)})
                continue
            seen_paths.add(path)
            try:
                data = stable_read(path)
                key = (path.name, digest(data))
                by_filename[path.name].append({"path": str(path), "sha256": key[1]})
                if key in by_content:
                    by_content[key]["paths"].append(str(path))
                    continue
                module = parse_module(path, data)
                by_content[key] = module
                report["modules"].append(module)
            except Exception as exc:
                report["errors"].append({
                    "kind": "module_parse_failure", "path": str(path),
                    "error": f"{type(exc).__name__}: {exc}",
                })
    modules = report["modules"]
    if args.expected_count is not None and len(seen_paths) != args.expected_count:
        report["errors"].append({"kind": "unexpected_file_count", "expected": args.expected_count,
                                 "actual": len(seen_paths)})
    for name, files in sorted(by_filename.items()):
        if len(files) > 1:
            conflict = len({f["sha256"] for f in files}) != 1
            report["duplicate_names"].append({"name": name, "different_hashes": conflict, "files": files})
            if conflict:
                report["errors"].append({"kind": "duplicate_filename_different_hash", "name": name})
    names = defaultdict(list)
    providers = defaultdict(list)
    for module in modules:
        names[module["module_name"]].append(module)
        if module["parse_errors"]:
            report["errors"].append({"kind": "module_export_parse_error", "module": module["module_name"],
                                     "errors": module["parse_errors"]})
        if module["vermagic"] != expected:
            report["errors"].append({"kind": "vermagic_mismatch", "module": module["module_name"],
                                     "actual": module["vermagic"], "expected": expected})
        if module["unversioned_strong_imports"]:
            report["errors"].append({"kind": "strong_import_missing_version", "module": module["module_name"],
                                     "symbols": module["unversioned_strong_imports"]})
        for name, export in module["exports"].items():
            providers[name].append({"module": module["module_name"], "file_name": module["file_name"],
                                    "sha256": module["sha256"], **export})
    for name, records in names.items():
        if len(records) > 1:
            report["errors"].append({"kind": "duplicate_module_identity", "name": name,
                                     "files": [m["file_name"] for m in records]})
    summary = Counter()
    issues_by_symbol = defaultdict(list)
    for module in modules:
        resolutions = {}
        for name, expected_crc in sorted(module["versions"].items()):
            result = {"expected_crc": expected_crc}
            if name in core:
                result["provider"] = {"core": True, **core[name]}
                status = "core_match" if expected_crc == core[name]["crc"] else "core_crc_mismatch"
            else:
                candidates = [p for p in providers.get(name, []) if p["sha256"] != module["sha256"]]
                result["providers"] = candidates
                if not candidates:
                    status = "missing_export"
                elif any(p["crc"] is None for p in candidates):
                    status = "module_export_crc_unresolved"
                elif any(p["crc"] != expected_crc for p in candidates):
                    status = "module_crc_mismatch"
                else:
                    status = "module_match"
                if candidates:
                    result["provider_ambiguity"] = len(candidates) > 1
            result["status"] = status
            resolutions[name] = result
            summary[status] += 1
            if status not in ("core_match", "module_match"):
                issue = {"module": module["module_name"], "file_name": module["file_name"],
                         "symbol": name, **result}
                issues_by_symbol[name].append(issue)
        module["import_resolution"] = resolutions
    for name, issues in sorted(issues_by_symbol.items()):
        report["errors"].append({"kind": "import_resolution_failure", "symbol": name, "references": issues})
    report["export_provider_collisions"] = {
        name: records for name, records in sorted(providers.items()) if len(records) > 1 or name in core
    }
    for name, records in report["export_provider_collisions"].items():
        report["errors"].append({"kind": "export_provider_collision", "symbol": name,
                                 "core_also_exports": name in core, "module_providers": records})
    stable_inputs = [(symvers, core_meta["sha256"])] + [
        (Path(value["path"]), value["sha256"])
        for value in evidence.values() if isinstance(value, dict) and "path" in value
    ]
    for path, expected_hash in stable_inputs:
        if digest(stable_read(path)) != expected_hash:
            report["errors"].append({"kind": "target_input_changed_during_audit", "path": str(path)})
    report["target_inputs_unchanged_at_end"] = not any(
        item["kind"] == "target_input_changed_during_audit" for item in report["errors"]
    )
    report["vermagic_distribution"] = dict(Counter(m["vermagic"] for m in modules))
    report["summary"] = {
        "input_files": len(seen_paths), "unique_file_name_and_hash": len(modules),
        "unique_module_names": len(names), "duplicate_file_names": len(report["duplicate_names"]),
        "different_hash_duplicate_names": sum(x["different_hashes"] for x in report["duplicate_names"]),
        "modules_parsed": len(modules), "core_exports": len(core),
        "module_exports": sum(len(m["exports"]) for m in modules),
        "unique_module_export_symbols": len(providers),
        "version_records": sum(len(m["versions"]) for m in modules),
        "import_resolution": dict(summary), "unresolved_symbols": len(issues_by_symbol),
        "error_groups": len(report["errors"]),
    }
    report["passed"] = not report["errors"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symvers", required=True, type=Path)
    parser.add_argument("--modules", required=True, nargs="+", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--expected-vermagic")
    args = parser.parse_args()
    try:
        report = audit(args)
    except Exception as exc:
        report = {"schema_version": 1, "passed": False,
                  "errors": [{"kind": "fatal_audit_error", "error": f"{type(exc).__name__}: {exc}"}]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(args.report),
                      "summary": report.get("summary"), "errors": report.get("errors") if "summary" not in report else None},
                     ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

