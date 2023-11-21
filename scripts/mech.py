from dataclasses import dataclass
import re
from typing import Any, Optional, List, Dict, Set
import requests
from web3 import Web3, HTTPProvider
from web3.datastructures import AttributeDict
from web3.types import BlockParams
from pathlib import Path
from eth_utils import to_checksum_address
from tqdm import tqdm

import json


HTTP = "http://"
HTTPS = HTTP[:4] + "s" + HTTP[4:]
CID_PREFIX = "f01701220"
IPFS_ADDRESS = f"{HTTPS}gateway.autonolas.tech/ipfs/"
MECH_CONTRACT_ADDRESSES = [
#    to_checksum_address("0xff82123dfb52ab75c417195c5fdb87630145ae81"), # Old Mech contract
    to_checksum_address("0x77af31de935740567cf4ff1986d04b2c964a786a")   # New Mech contract
]
IRRELEVANT_TOOLS = ["openai-text-davinci-002", "openai-text-davinci-003", "openai-gpt-3.5-turbo", "openai-gpt-4", "stabilityai-stable-diffusion-v1-5", "stabilityai-stable-diffusion-xl-beta-v2-2-2", "stabilityai-stable-diffusion-512-v2-1", "stabilityai-stable-diffusion-768-v2-1", "deepmind-optimization-strong", "deepmind-optimization"]

EARLIEST_BLOCK = 28911547


EARLIEST_BLOCK = 30663133  # New mech contract created.
# optionally set the latest block to stop searching for the delivered events
#LATEST_BLOCK: Optional[int] = 28991547
# LATEST_BLOCK: Optional[int] = None
#EARLIEST_BLOCK = 31029201
LATEST_BLOCK   = 31057341




LATEST_BLOCK_NAME: BlockParams = "latest"
BLOCK_DATA_NUMBER = "number"
BLOCKS_CHUNK_SIZE = 5_000


@dataclass
class MechBaseEvent:
    """Base class for mech's on-chain event representation."""

    # request_id: int
    # data: bytes

    # @property
    # def ipfs_link(self) -> Optional[str]:
    #     """Get the ipfs link."""
    #     if self.request_id is None:
    #         return None
    #     return f"{IPFS_ADDRESS}{CID_PREFIX}{self.data.hex()}/{self.request_id}"
    @classmethod
    def _get_ipfs_contents(cls, url: str) -> Dict[str, Any]:
        for _url in [f"{url}/metadata.json", url]:
            try:
                response = requests.get(_url)
                response.raise_for_status()
                ipfs_contents = response.json()
                return ipfs_contents
            except Exception:
                continue

        return {}


@dataclass
class MechDeliver(MechBaseEvent):
    """A mech's on-chain response representation."""

    event_name: str = "Deliver"


@dataclass
class MechRequest(MechBaseEvent):
    """A mech's on-chain response representation."""

    request_id: str
    data: str
    sender: str
    transaction_hash: str
    ipfs_link: str
    ipfs_contents: Dict[str, Any]
    nonce: str
    tool: str
    prompt: str
    fee: int
    event_name: str = "Request"

    def __init__(self, entry: AttributeDict):
        super().__init__()
        args = entry['args']
        self.request_id = args['requestId']
        self.data = args['data'].hex()
        self.sender = args['sender']
        self.event_name = entry['event']
        self.transaction_hash = entry['transactionHash'].hex()
        self.ipfs_link = f"{IPFS_ADDRESS}{CID_PREFIX}{self.data}"
        self.ipfs_contents = MechRequest._get_ipfs_contents(self.ipfs_link)
        self.nonce = self.ipfs_contents.get('nonce', '')
        self.tool = self.ipfs_contents.get('tool', '')
        prompt = self.ipfs_contents.get('prompt', '')
        prompt = prompt.replace('\n', ' ')
        prompt = prompt.strip()
        prompt = re.sub(r'\s+', ' ', prompt)
        self.prompt = prompt
        self.fee = 10000000000000000



def _get_mech_fee(w3: Web3, tx_hash) -> int:
    tx = w3.eth.get_transaction(tx_hash)
    print(tx)
    return 0


def _get_mech_events(rpc: str, mech_contract_address: str, event_name: str, starting_block: int, ending_block: int, sender: str, irrelevant_tools: Set[str]) -> List:
    """Get the mech Request events."""
    w3 = Web3(HTTPProvider(rpc))
    script_directory = Path(__file__).resolve().parent
    agent_mech_path = Path(script_directory, "..", "contracts", "AgentMech.json")

    with open(agent_mech_path, "r") as file:
        contract_data = json.load(file)

    abi = contract_data.get("abi", [])
    contract_instance = w3.eth.contract(address=mech_contract_address, abi=abi)

    if ending_block is None:
        ending_block = w3.eth.get_block(LATEST_BLOCK_NAME)[BLOCK_DATA_NUMBER]

    events = []
    for from_block in tqdm(
        range(starting_block, ending_block, BLOCKS_CHUNK_SIZE),
        desc=f"Searching Mech {event_name} events on the Gnosis chain...",
        unit="block chunks",
    ):
        to_block = min(from_block + BLOCKS_CHUNK_SIZE, ending_block)
        event_filter = contract_instance.events[event_name].create_filter(
            fromBlock=from_block, toBlock=to_block
        )
        chunk = event_filter.get_all_entries()
        w3.eth.uninstall_filter(event_filter.filter_id)
        filtered_events = [event for event in chunk if event['args']['sender'] == sender]
        events.extend(filtered_events)

    mech_requests = []
    for event in tqdm(
        events,
        desc=f"Reading metadata for the Mech {event_name} events on IPFS..."
    ):
        mech_request = MechRequest(event)
        if mech_request.tool not in irrelevant_tools:
            mech_requests.append(mech_request)

    return mech_requests

def get_mech_requests(rpc, sender):
    mech_requests = []

    for mech_contract_address in MECH_CONTRACT_ADDRESSES:
        mech_requests.extend(
            _get_mech_events(
                rpc,
                mech_contract_address,
                MechRequest.event_name,
                EARLIEST_BLOCK,
                None,
                sender,
                set(IRRELEVANT_TOOLS)
            )
        )
    return mech_requests
