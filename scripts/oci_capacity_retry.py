#!/usr/bin/env python3
"""
Retry-скрипт для захвата ARM-капасити на Oracle Cloud Free Tier.

Проблема: shape VM.Standard.A1.Flex (Always Free ARM) в популярных регионах
часто отдаёт ошибку "Out of host capacity". Место освобождается непредсказуемо
(минуты - недели). Скрипт пытается LaunchInstance по очереди во всех доступных
Availability Domains региона; при успехе шлёт push через ntfy.sh и пишет
маркер-файл в репозиторий, чтобы последующие запуски сразу выходили без работы.

Все секреты приходят через переменные окружения (GitHub Actions secrets).

Требуемые переменные окружения:
  OCI_USER_OCID           - OCID пользователя (из API Keys консоли)
  OCI_FINGERPRINT         - fingerprint API-ключа
  OCI_TENANCY_OCID        - OCID тенанси (rus3212)
  OCI_REGION              - например eu-frankfurt-1
  OCI_PRIVATE_KEY         - содержимое приватного API signing key (PEM), НЕ SSH-ключ инстанса
  OCI_COMPARTMENT_OCID    - OCID compartment (root тенанси, если отдельный не создавался)
  OCI_SUBNET_OCID         - OCID subnet (vcn-20260824-2154 / subnet-20260824-2154)
  OCI_AVAILABILITY_DOMAINS- список AD через запятую, например:
                            "kIdk:EU-FRANKFURT-1-AD-1,kIdk:EU-FRANKFURT-1-AD-2,kIdk:EU-FRANKFURT-1-AD-3"
  OCI_SSH_PUBLIC_KEY      - публичный SSH-ключ ИНСТАНСА (тот самый, который скачивали
                            на шаге "Add SSH keys" - не путать с API signing key выше)
  OCI_INSTANCE_DISPLAY_NAME (опционально) - имя инстанса, по умолчанию "weather-odessa-vps"
  NTFY_TOPIC_HEALTH       - тема ntfy.sh для уведомлений о здоровье пайплайна (уже используется проектом)

OCID образа НЕ передаётся секретом - скрипт сам находит самый свежий образ
Canonical Ubuntu 24.04, совместимый с shape VM.Standard.A1.Flex, через
ComputeClient.list_images (сортировка по времени создания, берём первый).
Это устраняет протухание OCID при обновлении образа Oracle и избавляет
от необходимости искать OCID вручную в консоли (которая на мобильном
интерфейсе не всегда показывает эту колонку).

Маркер успеха: data/oci_instance_created.json в репозитории. Если файл существует
и содержит instance_id - скрипт сразу завершается (капасити уже захвачена, инстанс создан).

Публикация маркер-файла - через GitHub Contents API (тот же паттерн GET sha -> PUT -> verify,
что используется во всём остальном пайплайне проекта).
"""

import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

GITHUB_REPO = "ruslan591/weather-_Odessa"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
MARKER_PATH = "data/oci_instance_created.json"


def gh_headers():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("REPO_PAT")
    if not token:
        raise RuntimeError("Нужен GITHUB_TOKEN или REPO_PAT в окружении для записи маркер-файла")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }


def gh_get_file(path):
    url = f"{GITHUB_API}/contents/{path}?ref=main"
    req = urllib.request.Request(url, headers=gh_headers())
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content, data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def gh_put_file(path, content_str, sha, message):
    url = f"{GITHUB_API}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=gh_headers(), method="PUT"
    )
    with urllib.request.urlopen(req) as resp:
        result = json.load(resp)
    # верификация: повторный GET, сверка sha + ключевого поля
    content2, sha2 = gh_get_file(path)
    if content2 is None or sha2 != result["content"]["sha"]:
        raise RuntimeError("Верификация маркер-файла после PUT не прошла")
    return result


def send_ntfy(topic, title, message, priority="high"):
    if not topic:
        print("NTFY_TOPIC_HEALTH не задан, пропускаю уведомление")
        return
    url = f"https://ntfy.sh/{topic}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": priority},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"ntfy отправка не удалась: {e}")


def get_latest_ubuntu_2404_image_id(compute_client, compartment_id):
    """Находит самый свежий образ Canonical Ubuntu 24.04, совместимый с A1.Flex."""
    import oci
    images = oci.pagination.list_call_get_all_results(
        compute_client.list_images,
        compartment_id=compartment_id,
        operating_system="Canonical Ubuntu",
        operating_system_version="24.04",
        shape="VM.Standard.A1.Flex",
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data
    if not images:
        raise RuntimeError(
            "Не найдено ни одного образа Canonical Ubuntu 24.04, "
            "совместимого с VM.Standard.A1.Flex"
        )
    chosen = images[0]
    print(f"Выбран образ: {chosen.display_name} ({chosen.id}), создан {chosen.time_created}")
    return chosen.id


def already_created():
    content, _ = gh_get_file(MARKER_PATH)
    if content is None:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def main():
    existing = already_created()
    if existing:
        print(f"Инстанс уже создан ранее: {existing.get('instance_id')} - выхожу без работы")
        sys.exit(0)

    try:
        import oci
    except ImportError:
        print("Пакет oci не установлен. В workflow должен быть шаг: pip install oci")
        sys.exit(1)

    required_env = [
        "OCI_USER_OCID", "OCI_FINGERPRINT", "OCI_TENANCY_OCID", "OCI_REGION",
        "OCI_PRIVATE_KEY", "OCI_COMPARTMENT_OCID", "OCI_SUBNET_OCID",
        "OCI_AVAILABILITY_DOMAINS", "OCI_SSH_PUBLIC_KEY",
    ]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        print(f"Не хватает секретов: {missing}. Скрипт не может работать без них.")
        sys.exit(1)

    config = {
        "user": os.environ["OCI_USER_OCID"],
        "fingerprint": os.environ["OCI_FINGERPRINT"],
        "tenancy": os.environ["OCI_TENANCY_OCID"],
        "region": os.environ["OCI_REGION"],
        "key_content": os.environ["OCI_PRIVATE_KEY"],
    }

    compute_client = oci.core.ComputeClient(config)
    ads = [a.strip() for a in os.environ["OCI_AVAILABILITY_DOMAINS"].split(",") if a.strip()]
    display_name = os.environ.get("OCI_INSTANCE_DISPLAY_NAME", "weather-odessa-vps")
    ntfy_topic = os.environ.get("NTFY_TOPIC_HEALTH")
    compartment_id = os.environ["OCI_COMPARTMENT_OCID"]

    image_id = get_latest_ubuntu_2404_image_id(compute_client, compartment_id)

    launch_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=compartment_id,
        display_name=display_name,
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=4,
            memory_in_gbs=24,
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id,
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=os.environ["OCI_SUBNET_OCID"],
            assign_public_ip=True,
        ),
        metadata={
            "ssh_authorized_keys": os.environ["OCI_SSH_PUBLIC_KEY"],
        },
    )

    last_error = None
    for ad in ads:
        launch_details.availability_domain = ad
        print(f"Пробую LaunchInstance в {ad}...")
        try:
            response = compute_client.launch_instance(launch_details)
            instance = response.data
            print(f"Успех! instance_id={instance.id}, ad={ad}")

            marker = {
                "instance_id": instance.id,
                "availability_domain": ad,
                "display_name": display_name,
                "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "lifecycle_state": instance.lifecycle_state,
            }
            _, sha = gh_get_file(MARKER_PATH)
            gh_put_file(
                MARKER_PATH,
                json.dumps(marker, indent=2, ensure_ascii=False),
                sha,
                "oci: инстанс создан, capacity retry завершён успешно",
            )

            send_ntfy(
                ntfy_topic,
                "Oracle VPS создан!",
                f"instance_id={instance.id}\nAD={ad}\n"
                f"Публичный IP появится через 1-2 минуты в консоли Oracle "
                f"(Compute -> Instances -> {display_name})",
            )
            print("Готово. Дальше: зайти в консоль Oracle, взять публичный IP, "
                  "передать Руслану для добавления в network settings Claude.")
            sys.exit(0)

        except oci.exceptions.ServiceError as e:
            last_error = e
            capacity_related = (
                e.status in (500, 429)
                or "OutOfCapacity" in (e.code or "")
                or "capacity" in (e.message or "").lower()
            )
            if capacity_related:
                print(f"{ad}: нет капасити ({e.code}), пробую следующий AD")
                continue
            else:
                print(f"{ad}: ошибка НЕ про капасити - {e.code}: {e.message}")
                send_ntfy(
                    ntfy_topic,
                    "OCI retry: неожиданная ошибка",
                    f"AD={ad}, code={e.code}, message={e.message}",
                    priority="urgent",
                )
                sys.exit(1)

    print(f"Капасити нет ни в одном AD ({ads}). Последняя ошибка: {last_error}")
    sys.exit(0)


if __name__ == "__main__":
    main()
