from gtools.core.growtopia.crypto import generate_rid
from gtools.proxy.accountmgr import Account


def up(acc: Account) -> Account:
    if "rid" not in acc["ident"]:
        acc["ident"]["rid"] = generate_rid()
    return acc
