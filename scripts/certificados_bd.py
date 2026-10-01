"""Certificados TLS para el PostgreSQL local (lo usa scripts/postgres.ps1 asegurar).

  python scripts/certificados_bd.py CARPETA_CERTIFICADOS CARPETA_DATOS_POSTGRES

Crea, si no existen, una autoridad propia (CARPETA_CERTIFICADOS/ca.crt y ca.key) y con ella un certificado de
servidor para localhost (CARPETA_DATOS_POSTGRES/server.crt y server.key). La app verifica el servidor con
ca.crt (DB_SSLMODE=verify-full), así que nadie puede hacerse pasar por la base de datos.
"""
import datetime
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_YEARS = 10
SERVER_YEARS = 2


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _write_key(path: Path, key) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))


def _load_or_create_ca(folder: Path):
    cert_path, key_path = folder / "ca.crt", folder / "ca.key"
    if cert_path.exists() and key_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        return x509.load_pem_x509_certificate(cert_path.read_bytes()), key
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ProyectoChats - autoridad de la base de datos")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - datetime.timedelta(minutes=5))
            .not_valid_after(_now() + datetime.timedelta(days=365 * CA_YEARS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    folder.mkdir(parents=True, exist_ok=True)
    _write_key(key_path, key)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def _create_server_cert(ca_cert, ca_key, data_dir: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
             x509.IPAddress(ipaddress.ip_address("::1"))]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - datetime.timedelta(minutes=5))
            .not_valid_after(_now() + datetime.timedelta(days=365 * SERVER_YEARS))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_key(data_dir / "server.key", key)
    (data_dir / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    certs, data_dir = Path(sys.argv[1]), Path(sys.argv[2])
    ca_cert, ca_key = _load_or_create_ca(certs)
    _create_server_cert(ca_cert, ca_key, data_dir)
    print(certs / "ca.crt")


if __name__ == "__main__":
    main()
