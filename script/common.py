from pymongo import MongoClient, ReadPreference
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern
import uuid


# ============================================================
# 目前环境已经搭好了
#
# mongo1:27017 -> PRIMARY
# mongo2:27018 -> 正常 SECONDARY
# mongo3:27019 -> 延迟 10 秒的 SECONDARY
#
# mongo3 设置了：
#   priority = 0
#   secondaryDelaySecs = 10
#   tag = role: delayed

# 实验脚本统一从这个文件拿连接和配置，
# ============================================================


DB_NAME = "dsa5208"
COLLECTION_NAME = "consistency_test"

DELAY_SECONDS = 10


# 正常连接 replica set。
# 写数据、正常读、causal session、故障实验都用这个。
NORMAL_URI = (
    "mongodb://mongo1:27017,mongo2:27018/"
    "?replicaSet=rs0"
    "&retryWrites=false"
)


# 如果实验需要故意读旧数据，就直接连 mongo3。
#
# mongo3 里面的数据大约比 primary 旧 10 秒。
#
# 比如刚写入 version=5：
#
#   mongo1 -> version 5
#   mongo2 -> version 5
#   mongo3 -> 可能还是 version 4
#
# 这时候马上读 mongo3，就可能读到旧数据。
DELAYED_URI = (
    "mongodb://mongo3:27019/"
    "?directConnection=true"
    "&retryWrites=false"
)


# ============================================================
# 四组实验配置
# ============================================================

CONFIGS = {
    "C1": {
        "read_concern": "majority",
        "write_concern": "majority",
    },

    "C2": {
        "read_concern": "majority",
        "write_concern": 1,
    },

    "C3": {
        "read_concern": "local",
        "write_concern": 1,
    },

    "C4": {
        "read_concern": "local",
        "write_concern": "majority",
    },
}


def get_normal_client():
    """
    正常实验用这个 client。

    比如：
    - 正常读写
    - causal session
    - primary 挂掉后的 election
    - network partition
    """

    return MongoClient(
        NORMAL_URI,
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
    )


def get_delayed_client():
    """
    想故意读 mongo3 的旧数据时用这个。

    主要给 RYW / MR 这种需要制造 stale read 的实验用。
    """

    return MongoClient(
        DELAYED_URI,
        read_preference=ReadPreference.SECONDARY,
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
    )


def get_collection(client, config_name, collection_name=COLLECTION_NAME):
    """
    根据 C1 / C2 / C3 / C4 创建对应的 collection。

    用法：
        client = get_normal_client()
        col = get_collection(client, "C3")
    """

    if config_name not in CONFIGS:
        raise ValueError(f"未知配置: {config_name}")

    config = CONFIGS[config_name]

    db = client.get_database(
        DB_NAME,
        read_concern=ReadConcern(
            config["read_concern"]
        ),
        write_concern=WriteConcern(
            w=config["write_concern"],
            wtimeout=5000,
        ),
    )

    return db[collection_name]


def new_trial_id(experiment_name):
    """
    每次实验生成一个新的 _id。
    """

    return f"{experiment_name}-{uuid.uuid4().hex}"