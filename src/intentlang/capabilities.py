"""Capability Registry: contratos, validacion y ejecucion de capabilities.

Una capability es una unidad de ejecucion con contrato definido:
- input/output schemas (JSON Schema)
- preconditions / postconditions
- side effects declarados
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import ValidationError, validate


@dataclass(frozen=True, slots=True)
class CapabilityContract:
    """Contrato de una capability."""
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)   # JSON Schema
    output_schema: dict = field(default_factory=dict)  # JSON Schema
    preconditions: list[Callable[[dict], bool]] = field(default_factory=list)
    postconditions: list[Callable[[dict], bool]] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)  # "filesystem", "network", "process", "crypto"


# Registry global
CAPABILITY_REGISTRY: dict[str, CapabilityContract] = {}
IMPLEMENTATIONS: dict[str, Callable[[dict], dict]] = {}


def register_capability(contract: CapabilityContract, 
                        implementation: Callable[[dict], dict] | None = None) -> None:
    """Registra una capability con su contrato y opcionalmente su implementacion."""
    CAPABILITY_REGISTRY[contract.name] = contract
    if implementation:
        IMPLEMENTATIONS[contract.name] = implementation


def get_contract(name: str) -> CapabilityContract | None:
    """Obtiene el contrato de una capability."""
    return CAPABILITY_REGISTRY.get(name)


def validate_inputs(name: str, inputs: dict) -> bool:
    """Valida inputs contra el contrato."""
    contract = CAPABILITY_REGISTRY.get(name)
    if not contract:
        return False
    
    # Validar input schema
    if contract.input_schema:
        try:
            validate(instance=inputs, schema=contract.input_schema)
        except ValidationError:
            return False
    
    # Validar preconditions
    for pre in contract.preconditions:
        if not pre(inputs):
            return False
    
    return True


def validate_outputs(name: str, outputs: dict) -> bool:
    """Valida outputs contra el contrato."""
    contract = CAPABILITY_REGISTRY.get(name)
    if not contract:
        return False
    
    if contract.output_schema:
        try:
            validate(instance=outputs, schema=contract.output_schema)
        except ValidationError:
            return False
    
    for post in contract.postconditions:
        if not post(outputs):
            return False
    
    return True


def execute_capability(name: str, inputs: dict) -> dict:
    """Ejecuta una capability validando contrato completo."""
    contract = CAPABILITY_REGISTRY.get(name)
    if not contract:
        raise ValueError(f"Capability not registered: {name}")
    
    impl = IMPLEMENTATIONS.get(name)
    if not impl:
        raise ValueError(f"No implementation for capability: {name}")
    
    # Validar preconditions
    if not validate_inputs(name, inputs):
        raise ValueError(f"Input validation failed for {name}")
    
    # Ejecutar
    try:
        result = impl(inputs)
    except Exception as e:
        raise RuntimeError(f"Capability {name} execution failed: {e}") from e
    
    # Validar postconditions
    if not validate_outputs(name, result):
        raise ValueError(f"Output validation failed for {name}")
    
    return result


# ============================================================
# Capabilities basicas incluidas (filesystem, process, query)
# ============================================================


def _cap_fs_copy(inputs: dict) -> dict:
    src = inputs["src"]
    dst = inputs["dst"]
    shutil.copy2(src, dst)
    return {"copied": True, "src": src, "dst": dst}


def _cap_fs_move(inputs: dict) -> dict:
    src = inputs["src"]
    dst = inputs["dst"]
    shutil.move(src, dst)
    return {"moved": True, "src": src, "dst": dst}


def _cap_fs_delete(inputs: dict) -> dict:
    path = inputs["path"]
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
    return {"deleted": True, "path": path}


def _cap_fs_write(inputs: dict) -> dict:
    path = inputs["path"]
    content = inputs.get("content", "")
    _mode = inputs.get("mode", "w")
    Path(path).write_text(content, encoding="utf-8")
    return {"written": True, "path": path, "bytes": len(content.encode("utf-8"))}


def _cap_fs_read(inputs: dict) -> dict:
    path = inputs["path"]
    content = Path(path).read_text(encoding="utf-8")
    return {"content": content, "path": path}


def _cap_fs_modify(inputs: dict) -> dict:
    """Modifica un archivo (append, replace, etc.)."""
    path = inputs["path"]
    operation = inputs.get("operation", "append")
    content = inputs.get("content", "")
    
    if operation == "append":
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    elif operation == "replace":
        Path(path).write_text(content, encoding="utf-8")
    else:
        raise ValueError(f"Unknown operation: {operation}")
    
    return {"modified": True, "path": path, "operation": operation}


def _cap_process_run(inputs: dict) -> dict:
    """Ejecuta un comando y captura salida."""
    cmd = inputs["cmd"]
    cwd = inputs.get("cwd")
    timeout = inputs.get("timeout", 30)
    capture = inputs.get("capture", True)
    
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, timeout=timeout,
        capture_output=capture, text=True, check=False
    )
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout if capture else "",
        "stderr": result.stderr if capture else "",
        "success": result.returncode == 0,
    }


def _cap_query_exec(inputs: dict) -> dict:
    """Ejecuta una query simple (placeholder para DB/SPARQL/etc)."""
    query = inputs["query"]
    # Placeholder: en produccion conectaria a DB real
    return {"query": query, "results": [], "row_count": 0}


def _cap_net_connect(inputs: dict) -> dict:
    """Test de conectividad de red basico."""
    import socket
    host = inputs["host"]
    port = inputs.get("port", 80)
    timeout = inputs.get("timeout", 5)
    
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return {"connected": True, "host": host, "port": port}
    except Exception as e:
        return {"connected": False, "host": host, "port": port, "error": str(e)}


def _cap_net_download(inputs: dict) -> dict:
    """Descarga un archivo via HTTP."""
    import urllib.request
    url = inputs["url"]
    dest = inputs["dest"]
    
    urllib.request.urlretrieve(url, dest)
    return {"downloaded": True, "url": url, "dest": dest, "size": os.path.getsize(dest)}


# ============================================================
# Crypto capabilities
# ============================================================

def _cap_crypto_hash(inputs: dict) -> dict:
    """Compute hash of file or string."""
    import hashlib
    data = inputs["data"]
    algorithm = inputs.get("algorithm", "sha256")
    is_file = inputs.get("is_file", False)
    
    hasher = hashlib.new(algorithm)
    if is_file:
        with open(data, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
    else:
        hasher.update(data.encode("utf-8"))
    
    return {"hash": hasher.hexdigest(), "algorithm": algorithm}


def _cap_crypto_encrypt(inputs: dict) -> dict:
    """Encrypt data with symmetric key (AES)."""
    import base64

    from cryptography.fernet import Fernet
    
    data = inputs["data"]
    key = inputs["key"]
    _algorithm = inputs.get("algorithm", "aes")
    
    # Derive key from password if needed
    if len(key) != 32:
        import hashlib
        key = hashlib.sha256(key.encode()).digest()
    
    f = Fernet(base64.urlsafe_b64encode(key))
    encrypted = f.encrypt(data.encode())
    
    return {
        "encrypted": base64.urlsafe_b64encode(encrypted).decode(),
        "algorithm": "fernet",
        "iv": ""  # Fernet handles IV internally
    }


def _cap_crypto_decrypt(inputs: dict) -> dict:
    """Decrypt data with symmetric key (AES)."""
    import base64

    from cryptography.fernet import Fernet
    
    encrypted = inputs["encrypted"]
    key = inputs["key"]
    _iv = inputs.get("iv", "")  # Fernet doesn't use separate IV
    _algorithm = inputs.get("algorithm", "aes")
    
    if len(key) != 32:
        import hashlib
        key = hashlib.sha256(key.encode()).digest()
    
    f = Fernet(base64.urlsafe_b64encode(key))
    decrypted = f.decrypt(base64.urlsafe_b64decode(encrypted))
    
    return {"data": decrypted.decode(), "algorithm": "fernet"}


def _cap_crypto_sign(inputs: dict) -> dict:
    """Sign data with private key (RSA/ECDSA placeholder)."""
    import base64
    import hashlib
    
    data = inputs["data"]
    private_key = inputs["private_key"]
    algorithm = inputs.get("algorithm", "rsa")
    
    # Placeholder: real implementation would use cryptography.hazmat
    signature = base64.b64encode(hashlib.sha256((data + private_key).encode()).digest()).decode()
    
    return {"signature": signature, "algorithm": algorithm}


def _cap_crypto_verify(inputs: dict) -> dict:
    """Verify signature with public key (placeholder)."""
    import base64
    import hashlib
    
    data = inputs["data"]
    signature = inputs["signature"]
    public_key = inputs["public_key"]
    algorithm = inputs.get("algorithm", "rsa")
    
    # Placeholder
    expected = base64.b64encode(hashlib.sha256((data + public_key).encode()).digest()).decode()
    valid = signature == expected
    
    return {"valid": valid, "algorithm": algorithm}


# ============================================================
# Media capabilities
# ============================================================

def _cap_media_render(inputs: dict) -> dict:
    """Render media (placeholder for ffmpeg/imagemagick)."""
    _source = inputs["source"]
    output = inputs["output"]
    format = inputs.get("format", "")
    _params = inputs.get("params", {})
    
    # Placeholder: real implementation would call ffmpeg/imagemagick
    return {"rendered": False, "output": output, "format": format, "placeholder": True}


def _cap_media_convert(inputs: dict) -> dict:
    """Convert media format (placeholder)."""
    _source = inputs["source"]
    output = inputs["output"]
    format = inputs["format"]
    
    # Placeholder
    return {"converted": False, "output": output, "format": format, "placeholder": True}


# ============================================================
# Build capabilities
# ============================================================

def _cap_build_compile(inputs: dict) -> dict:
    """Compile source code (gcc, rustc, etc.)."""
    import subprocess
    source = inputs["source"]
    output = inputs["output"]
    compiler = inputs.get("compiler", "gcc")
    flags = inputs.get("flags", [])
    
    cmd = [compiler, *flags, "-o", output, source]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    
    return {
        "compiled": result.returncode == 0,
        "output": output,
        "exit_code": result.returncode,
        "stderr": result.stderr,
    }


def _cap_build_test(inputs: dict) -> dict:
    """Run tests (pytest, cargo test, etc.)."""
    import subprocess
    path = inputs["path"]
    runner = inputs.get("runner", "pytest")
    args = inputs.get("args", [])
    
    cmd = [runner, *args, path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    
    return {
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ============================================================
# Archive capabilities
# ============================================================

def _cap_archive_create(inputs: dict) -> dict:
    """Create archive (tar.gz, zip)."""
    import tarfile
    import zipfile
    source = inputs["source"]
    output = inputs["output"]
    format = inputs.get("format", "tar.gz")
    
    if format == "tar.gz":
        with tarfile.open(output, "w:gz") as tar:
            tar.add(source, arcname=os.path.basename(source))
    elif format == "zip":
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.isdir(source):
                for root, _dirs, files in os.walk(source):
                    for file in files:
                        filepath = os.path.join(root, file)
                        arcname = os.path.relpath(filepath, os.path.dirname(source))
                        zf.write(filepath, arcname)
            else:
                zf.write(source, os.path.basename(source))
    
    return {
        "created": True,
        "output": output,
        "size": os.path.getsize(output),
    }


def _cap_archive_extract(inputs: dict) -> dict:
    """Extract archive (tar.gz, zip)."""
    import tarfile
    import zipfile
    archive = inputs["archive"]
    dest = inputs["dest"]
    
    extracted_files = []
    
    if archive.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest)
            extracted_files = tar.getnames()
    elif archive.endswith(".zip"):
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dest)
            extracted_files = zf.namelist()
    
    return {
        "extracted": True,
        "dest": dest,
        "files": extracted_files,
    }


# Registrar capabilities basicas
_basic_caps = [
    # Filesystem
    (CapabilityContract(
        name="cap.fs.copy",
        description="Copy file from src to dst",
        input_schema={"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]},
        output_schema={"type": "object", "properties": {"copied": {"type": "boolean"}, "src": {"type": "string"}, "dst": {"type": "string"}}},
        side_effects=["filesystem"],
    ), _cap_fs_copy),
    
    (CapabilityContract(
        name="cap.fs.move",
        description="Move file from src to dst",
        input_schema={"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]},
        output_schema={"type": "object", "properties": {"moved": {"type": "boolean"}, "src": {"type": "string"}, "dst": {"type": "string"}}},
        side_effects=["filesystem"],
    ), _cap_fs_move),
    
    (CapabilityContract(
        name="cap.fs.delete",
        description="Delete file or directory",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        output_schema={"type": "object", "properties": {"deleted": {"type": "boolean"}, "path": {"type": "string"}}},
        side_effects=["filesystem"],
    ), _cap_fs_delete),
    
    (CapabilityContract(
        name="cap.fs.write",
        description="Write content to file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "mode": {"type": "string"}}, "required": ["path", "content"]},
        output_schema={"type": "object", "properties": {"written": {"type": "boolean"}, "path": {"type": "string"}, "bytes": {"type": "integer"}}},
        side_effects=["filesystem"],
    ), _cap_fs_write),
    
    (CapabilityContract(
        name="cap.fs.read",
        description="Read content from file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        output_schema={"type": "object", "properties": {"content": {"type": "string"}, "path": {"type": "string"}}},
        side_effects=["filesystem"],
    ), _cap_fs_read),
    
    (CapabilityContract(
        name="cap.fs.modify",
        description="Modify file (append/replace)",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}, "operation": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "operation", "content"]},
        output_schema={"type": "object", "properties": {"modified": {"type": "boolean"}, "path": {"type": "string"}, "operation": {"type": "string"}}},
        side_effects=["filesystem"],
    ), _cap_fs_modify),
    
    # Process
    (CapabilityContract(
        name="cap.process.run",
        description="Run shell command",
        input_schema={"type": "object", "properties": {"cmd": {"type": "string"}, "cwd": {"type": "string"}, "timeout": {"type": "integer"}, "capture": {"type": "boolean"}}, "required": ["cmd"]},
        output_schema={"type": "object", "properties": {"exit_code": {"type": "integer"}, "stdout": {"type": "string"}, "stderr": {"type": "string"}, "success": {"type": "boolean"}}},
        side_effects=["process"],
    ), _cap_process_run),
    
    # Query
    (CapabilityContract(
        name="cap.query.exec",
        description="Execute query",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        output_schema={"type": "object", "properties": {"query": {"type": "string"}, "results": {"type": "array"}, "row_count": {"type": "integer"}}},
        side_effects=[],
    ), _cap_query_exec),
    
    # Network
    (CapabilityContract(
        name="cap.net.connect",
        description="Test network connectivity",
        input_schema={"type": "object", "properties": {"host": {"type": "string"}, "port": {"type": "integer"}, "timeout": {"type": "integer"}}, "required": ["host"]},
        output_schema={"type": "object", "properties": {"connected": {"type": "boolean"}, "host": {"type": "string"}, "port": {"type": "integer"}, "error": {"type": "string"}}},
        side_effects=["network"],
    ), _cap_net_connect),
    
    (CapabilityContract(
        name="cap.net.download",
        description="Download file via HTTP",
        input_schema={"type": "object", "properties": {"url": {"type": "string"}, "dest": {"type": "string"}}, "required": ["url", "dest"]},
        output_schema={"type": "object", "properties": {"downloaded": {"type": "boolean"}, "url": {"type": "string"}, "dest": {"type": "string"}, "size": {"type": "integer"}}},
        side_effects=["network", "filesystem"],
    ), _cap_net_download),
    
    # Crypto
    (CapabilityContract(
        name="cap.crypto.hash",
        description="Compute hash of file or string",
        input_schema={"type": "object", "properties": {"data": {"type": "string"}, "algorithm": {"type": "string", "enum": ["md5", "sha1", "sha256", "sha512"]}, "is_file": {"type": "boolean"}}, "required": ["data"]},
        output_schema={"type": "object", "properties": {"hash": {"type": "string"}, "algorithm": {"type": "string"}}},
        side_effects=["crypto"],
    ), _cap_crypto_hash),
    
    (CapabilityContract(
        name="cap.crypto.encrypt",
        description="Encrypt data with symmetric key",
        input_schema={"type": "object", "properties": {"data": {"type": "string"}, "key": {"type": "string"}, "algorithm": {"type": "string", "enum": ["aes"]}}, "required": ["data", "key"]},
        output_schema={"type": "object", "properties": {"encrypted": {"type": "string"}, "algorithm": {"type": "string"}, "iv": {"type": "string"}}},
        side_effects=["crypto"],
    ), _cap_crypto_encrypt),
    
    (CapabilityContract(
        name="cap.crypto.decrypt",
        description="Decrypt data with symmetric key",
        input_schema={"type": "object", "properties": {"encrypted": {"type": "string"}, "key": {"type": "string"}, "iv": {"type": "string"}, "algorithm": {"type": "string", "enum": ["aes"]}}, "required": ["encrypted", "key", "iv"]},
        output_schema={"type": "object", "properties": {"data": {"type": "string"}, "algorithm": {"type": "string"}}},
        side_effects=["crypto"],
    ), _cap_crypto_decrypt),
    
    (CapabilityContract(
        name="cap.crypto.sign",
        description="Sign data with private key",
        input_schema={"type": "object", "properties": {"data": {"type": "string"}, "private_key": {"type": "string"}, "algorithm": {"type": "string", "enum": ["rsa", "ecdsa"]}}, "required": ["data", "private_key"]},
        output_schema={"type": "object", "properties": {"signature": {"type": "string"}, "algorithm": {"type": "string"}}},
        side_effects=["crypto"],
    ), _cap_crypto_sign),
    
    (CapabilityContract(
        name="cap.crypto.verify",
        description="Verify signature with public key",
        input_schema={"type": "object", "properties": {"data": {"type": "string"}, "signature": {"type": "string"}, "public_key": {"type": "string"}, "algorithm": {"type": "string", "enum": ["rsa", "ecdsa"]}}, "required": ["data", "signature", "public_key"]},
        output_schema={"type": "object", "properties": {"valid": {"type": "boolean"}, "algorithm": {"type": "string"}}},
        side_effects=["crypto"],
    ), _cap_crypto_verify),
    
    # Media
    (CapabilityContract(
        name="cap.media.render",
        description="Render media (placeholder for ffmpeg/imagemagick)",
        input_schema={"type": "object", "properties": {"source": {"type": "string"}, "output": {"type": "string"}, "format": {"type": "string"}, "params": {"type": "object"}}, "required": ["source", "output"]},
        output_schema={"type": "object", "properties": {"rendered": {"type": "boolean"}, "output": {"type": "string"}}},
        side_effects=["media", "filesystem"],
    ), _cap_media_render),
    
    (CapabilityContract(
        name="cap.media.convert",
        description="Convert media format (placeholder)",
        input_schema={"type": "object", "properties": {"source": {"type": "string"}, "output": {"type": "string"}, "format": {"type": "string"}}, "required": ["source", "output", "format"]},
        output_schema={"type": "object", "properties": {"converted": {"type": "boolean"}, "output": {"type": "string"}}},
        side_effects=["media", "filesystem"],
    ), _cap_media_convert),
    
    # Build
    (CapabilityContract(
        name="cap.build.compile",
        description="Compile source code (gcc, rustc, etc.)",
        input_schema={"type": "object", "properties": {"source": {"type": "string"}, "output": {"type": "string"}, "compiler": {"type": "string"}, "flags": {"type": "array", "items": {"type": "string"}}}, "required": ["source", "output"]},
        output_schema={"type": "object", "properties": {"compiled": {"type": "boolean"}, "output": {"type": "string"}, "exit_code": {"type": "integer"}, "stderr": {"type": "string"}}},
        side_effects=["build", "filesystem", "process"],
    ), _cap_build_compile),
    
    (CapabilityContract(
        name="cap.build.test",
        description="Run tests (pytest, cargo test, etc.)",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}, "runner": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}}, "required": ["path"]},
        output_schema={"type": "object", "properties": {"passed": {"type": "boolean"}, "exit_code": {"type": "integer"}, "stdout": {"type": "string"}, "stderr": {"type": "string"}}},
        side_effects=["build", "process"],
    ), _cap_build_test),
    
    # Archive
    (CapabilityContract(
        name="cap.archive.create",
        description="Create archive (tar, zip)",
        input_schema={"type": "object", "properties": {"source": {"type": "string"}, "output": {"type": "string"}, "format": {"type": "string", "enum": ["tar.gz", "zip"]}}, "required": ["source", "output"]},
        output_schema={"type": "object", "properties": {"created": {"type": "boolean"}, "output": {"type": "string"}, "size": {"type": "integer"}}},
        side_effects=["archive", "filesystem"],
    ), _cap_archive_create),
    
    (CapabilityContract(
        name="cap.archive.extract",
        description="Extract archive (tar, zip)",
        input_schema={"type": "object", "properties": {"archive": {"type": "string"}, "dest": {"type": "string"}}, "required": ["archive", "dest"]},
        output_schema={"type": "object", "properties": {"extracted": {"type": "boolean"}, "dest": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}}}},
        side_effects=["archive", "filesystem"],
    ), _cap_archive_extract),
]

for contract, impl in _basic_caps:
    register_capability(contract, impl)


def list_capabilities() -> list[str]:
    """Lista todas las capabilities registradas."""
    return sorted(CAPABILITY_REGISTRY.keys())


def get_capability_info(name: str) -> dict | None:
    """Info completa de una capability."""
    contract = CAPABILITY_REGISTRY.get(name)
    if not contract:
        return None
    return {
        "name": contract.name,
        "description": contract.description,
        "input_schema": contract.input_schema,
        "output_schema": contract.output_schema,
        "side_effects": contract.side_effects,
        "has_implementation": name in IMPLEMENTATIONS,
    }
