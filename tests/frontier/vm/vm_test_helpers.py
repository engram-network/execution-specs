import json
import os
from functools import partial
from typing import Any

from ethereum.base_types import U256, Uint
from ethereum.crypto import keccak256
from ethereum.frontier import rlp
from ethereum.frontier.eth_types import Account
from ethereum.frontier.spec import BlockChain, get_recent_block_hashes
from ethereum.frontier.state import (
    State,
    set_account,
    set_storage,
    storage_root,
)
from ethereum.frontier.vm import Environment
from ethereum.frontier.vm.interpreter import process_call
from ethereum.utils.hexadecimal import (
    hex_to_address,
    hex_to_bytes,
    hex_to_bytes32,
    hex_to_u256,
    hex_to_uint,
)


def run_test(test_dir: str, test_file: str) -> None:
    test_data = load_test(test_dir, test_file)
    target = test_data["target"]
    env = test_data["env"]

    gas_left, logs = process_call(
        caller=test_data["caller"],
        target=target,
        data=test_data["data"],
        value=test_data["value"],
        gas=test_data["gas"],
        depth=test_data["depth"],
        env=env,
    )

    assert gas_left == test_data["expected_gas_left"]
    assert keccak256(rlp.encode(logs)) == test_data["expected_logs_hash"]
    # We are checking only the storage here and not the whole state, as the
    # balances in the testcases don't change even though some value is
    # transferred along with code invocation. But our evm execution transfers
    # the value as well as executing the code
    for addr in test_data["expected_post_state"]._storage_tries:
        assert storage_root(
            test_data["expected_post_state"], addr
        ) == storage_root(env.state, addr)


def load_test(test_dir: str, test_file: str) -> Any:
    test_name = os.path.splitext(test_file)[0]
    path = os.path.join(test_dir, test_file)
    with open(path, "r") as fp:
        json_data = json.load(fp)[test_name]

    env = json_to_env(json_data)

    return {
        "caller": hex_to_address(json_data["exec"]["caller"]),
        "target": hex_to_address(json_data["exec"]["address"]),
        "data": hex_to_bytes(json_data["exec"]["data"]),
        "value": hex_to_u256(json_data["exec"]["value"]),
        "gas": hex_to_u256(json_data["exec"]["gas"]),
        "depth": Uint(0),
        "env": env,
        "expected_gas_left": hex_to_u256(json_data.get("gas", "0x64")),
        "expected_logs_hash": hex_to_bytes(json_data.get("logs", "0x00")),
        "expected_post_state": json_to_state(json_data.get("post", {})),
    }


def json_to_env(json_data: Any) -> Environment:
    caller_hex_address = json_data["exec"]["caller"]
    # Some tests don't have the caller state defined in the test case. Hence
    # creating a dummy caller state.
    if caller_hex_address not in json_data["pre"]:
        value = json_data["exec"]["value"]
        json_data["pre"][caller_hex_address] = get_dummy_account_state(value)

    current_state = json_to_state(json_data["pre"])

    chain = BlockChain(
        blocks=[],
        state=current_state,
    )

    return Environment(
        caller=hex_to_address(json_data["exec"]["caller"]),
        origin=hex_to_address(json_data["exec"]["origin"]),
        block_hashes=get_recent_block_hashes(chain, Uint(256)),
        coinbase=hex_to_address(json_data["env"]["currentCoinbase"]),
        number=hex_to_uint(json_data["env"]["currentNumber"]),
        gas_limit=hex_to_uint(json_data["env"]["currentGasLimit"]),
        gas_price=hex_to_u256(json_data["exec"]["gasPrice"]),
        time=hex_to_u256(json_data["env"]["currentTimestamp"]),
        difficulty=hex_to_uint(json_data["env"]["currentDifficulty"]),
        state=current_state,
    )


def json_to_state(raw: Any) -> State:
    state = State()
    for (addr_hex, acc_state) in raw.items():
        addr = hex_to_address(addr_hex)
        account = Account(
            nonce=hex_to_uint(acc_state.get("nonce", "0x0")),
            balance=U256(hex_to_uint(acc_state.get("balance", "0x0"))),
            code=hex_to_bytes(acc_state.get("code", "")),
        )
        set_account(state, addr, account)

        for (k, v) in acc_state.get("storage", {}).items():
            set_storage(
                state,
                addr,
                hex_to_bytes32(k),
                U256.from_be_bytes(hex_to_bytes32(v)),
            )

        set_account(state, addr, account)

    return state


def get_dummy_account_state(min_balance: str) -> Any:
    # dummy account balance is the min balance needed plus 1 eth for gas
    # cost
    account_balance = hex_to_uint(min_balance) + (10 ** 18)

    return {
        "balance": hex(account_balance),
        "code": "",
        "nonce": "0x00",
        "storage": {},
    }
