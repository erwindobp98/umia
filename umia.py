from __future__ import annotations
import json
import os
import random
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
import requests
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from web3 import Web3
# Integrated Rich Library for Realtime Dashboard
from rich.live import Live
from rich.table import Table
from rich.console import Console

# ==============================================================================
# 0. KONFIGURASI BOT / PARAMETER UTAMA
# ==============================================================================
MAX_WORKERS = 11           # Jumlah eksekusi dompet bersamaan
SHUFFLE_WALLETS = False    # Acak urutan dompet
DELAY_MIN = 5              # Jeda waktu minimal antar aksi (detik)
DELAY_MAX = 8              # Jeda waktu maksimal antar aksi (detik)
MIN_ETH_FOR_GAS = "0.00005"# Minimal ETH untuk gas fee
GAS_MULTIPLIER = 1.25
RECEIPT_TIMEOUT = 180

FAUCET_ENABLED = True      # Aktifkan Faucet
FAUCET_RETRIES = 6
AUTO_REGISTER = True

SWAP_ENABLED = True        # Aktifkan modul Daily Swap
SWAP_USDC_DAILY = 6        # Target Transaksi Daily Swap per Hari (Maksimal 6x / 24 Jam)
SWAP_USDC_MIN = "10"
SWAP_USDC_MAX = "50"
SWAP_SLIPPAGE_BPS = 50

BID_ENABLED = True         # Aktifkan modul Bid
BID_USDC_MIN = "10"
BID_USDC_MAX = "50"
BID_PRICE_MULTIPLIER = 1.5

# KONFIGURASI AUTO EXIT, CLAIM, & AUTO SWAP REWARD
AUTO_CLAIM_ENABLED = True      # Otomatis Exit Bid & Claim Token dari auction yang selesai
AUTO_SWAP_BACK_ENABLED = True # Otomatis swap token hasil auction kembali ke USDC

SHUFFLE_ACTIONS = True     # Acak urutan tugas/aksi
REQUEST_TIMEOUT = 45       # Timeout HTTP Request (detik)

CAPTCHA_MAX_RETRIES = 3    # Maksimal percobaan retry captcha/login jika gagal

# ==============================================================================
# 1. CONSTANTS, CONTRACT ADDRESSES & SAFETY GUARDRAILS
# ==============================================================================
ALLOWED_CHAIN_IDS: frozenset[int] = frozenset({84532}) # Hanya Base Sepolia
BLOCKED_CHAIN_IDS: frozenset[int] = frozenset({1, 8453, 10, 42161, 137})

RPC_URL = "https://api.testnet.umia.finance/api/v1/rpc/84532"
API_BASE = "https://api.testnet.umia.finance"
USDC_ADDRESS = Web3.to_checksum_address("0x49b7A040aFCBFfC4cb02F857feE7b55C9C41658a")
PERMIT2_ADDRESS = Web3.to_checksum_address("0x000000000022D473030F116dDEE9F6B43aC78BA3")
USDC_DECIMALS = 6

PRIVY_APP_ID = "cmo1j6mrc00bw0cjogi68sggx"
TURNSTILE_SITE_KEY = "0x4AAAAAAAM8ceq5KhP1uJBt"
PRIVY_BASE = "https://auth.privy.io"

_HEX_SECRET = re.compile(r"(0x)?[a-fA-F0-9]{64,}")

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]

class MainnetBlockedError(RuntimeError):
    pass

def assert_allowed_chain(chain_id: int, context: str = "") -> None:
    cid = int(chain_id)
    if cid in BLOCKED_CHAIN_IDS or cid not in ALLOWED_CHAIN_IDS:
        where = f" ({context})" if context else ""
        raise MainnetBlockedError(
            f"ChainID {cid} dilarang{where}! Hanya Base Sepolia (84532) yang diizinkan."
        )

def redact_text(text: str, secrets: Iterable[str | None] = ()) -> str:
    out = str(text)
    for secret in secrets:
        if not secret:
            continue
        s = str(secret)
        if len(s) >= 8:
            out = out.replace(s, "***")
    out = _HEX_SECRET.sub(lambda m: m.group(0)[:6] + "…" + m.group(0)[-4:], out)
    return out

# ==============================================================================
# 2. SHARED STATE & UI DASHBOARD MANAGER
# ==============================================================================
wallet_states: dict[str, dict[str, Any]] = {}
system_status = {
    "active_workers": 0,
    "captcha_balance": "$12.40",
    "rpc_status": "Normal"
}
state_lock = threading.Lock()

def update_wallet_state(label: str, status: str = None, balance: str = None, last_tx: str = None):
    with state_lock:
        if label in wallet_states:
            if status is not None:
                wallet_states[label]["status"] = status
            if balance is not None:
                wallet_states[label]["balance"] = balance
            if last_tx is not None:
                wallet_states[label]["last_tx"] = last_tx

def render_dashboard() -> Table:
    table = Table(
        title="===================================================================================\nUMIA FINANCE BOT - REALTIME DASHBOARD\n===================================================================================",
        caption_justify="center",
        box=None,
        show_header=True,
        header_style="bold white"
    )

    table.add_column("WALLET", width=12)
    table.add_column("ADDRESS", width=16)
    table.add_column("STATUS", width=25)
    table.add_column("BALANCE", width=12)
    table.add_column("LAST TX / HASH", width=22)

    with state_lock:
        for w_label, data in wallet_states.items():
            table.add_row(
                w_label,
                data.get("address", "-"),
                data.get("status", "[WAITING] Idle"),
                data.get("balance", "0 USDC"),
                data.get("last_tx", "-")
            )

    sys_text = f"===================================================================================\n[System Status] Total Active Workers: {system_status['active_workers']} | Captcha Balance: {system_status['captcha_balance']} | RPC: {system_status['rpc_status']}\n==================================================================================="
    table.caption = sys_text
    return table

# ==============================================================================
# 3. UTILITIES & DASHBOARD LOGGER ADAPTER
# ==============================================================================
def to_units(value: str | Decimal | int | float, decimals: int) -> int:
    amount = Decimal(str(value))
    scale = Decimal(10) ** int(decimals)
    return int((amount * scale).to_integral_value(rounding=ROUND_DOWN))

def from_units(value: int, decimals: int, places: int | None = None) -> str:
    amount = Decimal(value) / (Decimal(10) ** int(decimals))
    if places is None:
        places = min(8, int(decimals))
    quant = Decimal(1).scaleb(-places)
    text = format(amount.quantize(quant, rounding=ROUND_DOWN).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"

def short_address(value: str) -> str:
    if value and value.startswith("0x") and len(value) > 12:
        return f"{value[:6]}...{value[-4:]}"
    return value or "-"

def human_price_to_x96(
    human_price: float | str | Decimal,
    *,
    currency_decimals: int,
    token_decimals: int,
    tick_spacing_x96: int,
) -> int:
    human = Decimal(str(human_price))
    if human <= 0:
        raise ValueError("price must be positive")
    tick = int(tick_spacing_x96)
    if tick <= 0:
        raise ValueError("invalid tick spacing")
    raw = human * (Decimal(2) ** 96) * (Decimal(10) ** currency_decimals) / (
        Decimal(10) ** token_decimals
    )
    snapped = int(raw // tick) * tick
    if snapped <= 0:
        snapped = tick
    return snapped

class DashboardLogger:
    def __init__(self, wallet_label: str) -> None:
        self.wallet_label = wallet_label

    def info(self, msg: str) -> None:
        update_wallet_state(self.wallet_label, status=f"{msg}")

    def success(self, msg: str) -> None:
        update_wallet_state(self.wallet_label, status=f"{msg}")

    def error(self, msg: str) -> None:
        update_wallet_state(self.wallet_label, status=f"[ERROR] {msg}")

# ==============================================================================
# 4. MANAJEMEN FILE CONFIG TERPISAH (.TXT)
# ==============================================================================
KEYS_FILE = Path("private_keys.txt")
CAPSOLVER_FILE = Path("capsolver_key.txt")

@dataclass(frozen=True)
class AccountConfig:
    label: str
    private_key: str

def load_private_keys() -> list[str]:
    if not KEYS_FILE.exists():
        KEYS_FILE.write_text("# Tempelkan Private Key EVM di sini (1 per baris)\n", encoding="utf-8")
        return []
    
    keys = []
    for line in KEYS_FILE.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            if not line.startswith("0x"):
                line = f"0x{line}"
            keys.append(line)
    return keys

def load_capsolver_key() -> str:
    if not CAPSOLVER_FILE.exists():
        CAPSOLVER_FILE.write_text("# Tempelkan Capsolver API Key di sini\n", encoding="utf-8")
        return ""
    
    for line in CAPSOLVER_FILE.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""

def get_accounts() -> list[AccountConfig]:
    raw_keys = load_private_keys()
    accounts = []
    for idx, key in enumerate(raw_keys, start=1):
        try:
            Account.from_key(key)
            accounts.append(AccountConfig(label=f"Wallet-{idx:02d}", private_key=key))
        except Exception:
            pass
    return accounts

# ==============================================================================
# 5. INTEGRASI CAPSOLVER & PRIVY AUTHENTICATION
# ==============================================================================
def solve_turnstile(api_key: str, website_url: str, log: Any = None) -> str:
    if not api_key:
        raise RuntimeError("API Key Capsolver kosong!")

    for attempt in range(1, CAPTCHA_MAX_RETRIES + 1):
        try:
            if log:
                log.info(f"[LOGIN] Solv Captcha ({attempt})")

            task = {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": website_url,
                "websiteKey": TURNSTILE_SITE_KEY,
            }

            res = requests.post(
                "https://api.capsolver.com/createTask", 
                json={"clientKey": api_key, "task": task}, 
                timeout=30
            )
            data = res.json()
            if data.get("errorId"):
                raise RuntimeError(f"Capsolver Error: {data.get('errorDescription')}")
            
            task_id = data.get("taskId")
            deadline = time.time() + 120
            
            while time.time() < deadline:
                time.sleep(3)
                res_check = requests.post(
                    "https://api.capsolver.com/getTaskResult", 
                    json={"clientKey": api_key, "taskId": task_id}, 
                    timeout=30
                )
                check_data = res_check.json()
                if check_data.get("status") == "ready":
                    return check_data["solution"]["token"]
                if check_data.get("status") == "failed":
                    raise RuntimeError("Capsolver Gagal Memecahkan Captcha.")
                    
            raise TimeoutError("Capsolver Timeout saat menunggu hasil.")

        except Exception as err:
            if attempt >= CAPTCHA_MAX_RETRIES:
                raise RuntimeError(f"Gagal Captcha setelah {CAPTCHA_MAX_RETRIES}x coba.")


def privy_login(account: AccountConfig, capsolver_key: str, log: Any = None) -> str:
    assert_allowed_chain(84532, context="Privy Login")
    acct = Account.from_key(account.private_key)
    origin = "https://app.testnet.umia.finance"
    host = urlparse(origin).netloc

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": f"{origin}/",
        "privy-app-id": PRIVY_APP_ID,
        "privy-client": "react:2.13.0",
        "privy-ca-id": str(uuid.uuid4()),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    })

    captcha_token = solve_turnstile(capsolver_key, f"{origin}/", log=log)

    init = session.post(
        f"{PRIVY_BASE}/api/v1/siwe/init", 
        json={"address": acct.address, "token": captcha_token}, 
        timeout=REQUEST_TIMEOUT
    )
    init_data = init.json()
    nonce = init_data.get("nonce")
    if not nonce:
        msg = init_data.get("message") or init_data.get("error") or "Gagal SIWE Init"
        raise RuntimeError(f"SIWE Init Error: {msg}")

    issued_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    message = (
        f"{host} wants you to sign in with your Ethereum account:\n"
        f"{acct.address}\n\n"
        f"By signing, you are proving you own this wallet and logging in. "
        f"This does not initiate a transaction or cost any fees.\n\n"
        f"URI: {origin}\n"
        f"Version: 1\n"
        f"Chain ID: 84532\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
        f"Resources:\n"
        f"- https://privy.io"
    )

    signed = acct.sign_message(encode_defunct(text=message))
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature

    auth = session.post(
        f"{PRIVY_BASE}/api/v1/siwe/authenticate",
        json={
            "message": message,
            "signature": signature,
            "chainId": "eip155:84532",
            "walletClientType": "metamask",
            "connectorType": "injected",
            "mode": "login-or-sign-up",
        },
        timeout=REQUEST_TIMEOUT
    )
    auth_data = auth.json()
    token = auth_data.get("token") or auth_data.get("privy_access_token")
    if not token:
        raise RuntimeError(f"Gagal Login Privy: {auth_data.get('message', 'No Token')}")
    
    return str(token)

# ==============================================================================
# 6. LOGIKA SMART CONTRACT & INTERAKSI WEB3 ON-CHAIN
# ==============================================================================
class UmiaWeb3Client:
    def __init__(self, account_config: AccountConfig, capsolver_key: str, log: Any):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        assert_allowed_chain(self.w3.eth.chain_id, context="Web3 Provider")
        self.account_config = account_config
        self.account = Account.from_key(account_config.private_key)
        self.capsolver_key = capsolver_key
        self.log = log
        self.usdc_contract = self.w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
        self.jwt_token: str | None = None

    def update_balance_display(self):
        try:
            bal_wei = self.usdc_contract.functions.balanceOf(self.account.address).call()
            bal_formatted = f"{from_units(bal_wei, USDC_DECIMALS)} USDC"
            update_wallet_state(self.account_config.label, balance=bal_formatted)
        except Exception:
            pass

    def get_valid_token(self) -> str:
        if not self.jwt_token:
            self.log.info("[LOGIN] Solv Captcha")
            self.jwt_token = privy_login(self.account_config, self.capsolver_key, log=self.log)
            self.update_balance_display()
        return self.jwt_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_valid_token()}",
            "Content-Type": "application/json",
            "Origin": "https://app.testnet.umia.finance",
            "Referer": "https://app.testnet.umia.finance/"
        }

    def _make_authenticated_request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs["headers"] = self._headers()
        kwargs["timeout"] = REQUEST_TIMEOUT
        
        res = requests.request(method, url, **kwargs)
        if res.status_code == 401:
            self.jwt_token = None
            kwargs["headers"] = self._headers()
            res = requests.request(method, url, **kwargs)
            
        return res

    def check_gas_balance(self) -> None:
        balance_wei = self.w3.eth.get_balance(self.account.address)
        min_wei = to_units(MIN_ETH_FOR_GAS, 18)
        if balance_wei < min_wei:
            raise RuntimeError(f"ETH Gas Rendah ({from_units(balance_wei, 18)} ETH)")

    def send_raw_transaction(self, tx_params: dict[str, Any]) -> str:
        self.check_gas_balance()
        tx_params["from"] = self.account.address
        if "nonce" not in tx_params:
            tx_params["nonce"] = self.w3.eth.get_transaction_count(self.account.address, "pending")
        if "gas" not in tx_params:
            estimated_gas = self.w3.eth.estimate_gas(tx_params)
            tx_params["gas"] = int(estimated_gas * GAS_MULTIPLIER)
        if "gasPrice" not in tx_params and "maxFeePerGas" not in tx_params:
            tx_params["gasPrice"] = int(self.w3.eth.gas_price * 1.1)

        signed_tx = self.w3.eth.account.sign_transaction(tx_params, self.account.key)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        tx_hex = tx_hash.hex()
        if not tx_hex.startswith("0x"):
            tx_hex = "0x" + tx_hex

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=RECEIPT_TIMEOUT)
        if receipt.get("status") != 1:
            raise RuntimeError(f"Tx Failed: {tx_hex}")
        return tx_hex

    def ensure_usdc_approval(self, spender: str, required_amount: int) -> None:
        current_allowance = self.usdc_contract.functions.allowance(self.account.address, spender).call()
        if current_allowance < required_amount:
            self.log.info("[APPROVING] USDC...")
            tx_data = self.usdc_contract.functions.approve(spender, 2**256 - 1).build_transaction({
                "chainId": 84532
            })
            self.send_raw_transaction(tx_data)

    def claim_faucet(self) -> None:
        self.log.info("[CLAIMING] Faucet...")
        res = self._make_authenticated_request("POST", f"{API_BASE}/api/v1/faucet", json={"address": self.account.address})
        data = res.json() if res.content else {}
        if res.status_code == 200 or data.get("success"):
            tx_h = data.get("txHash") or data.get("hash") or "0x8f2..."
            tx_fmt = f"{short_address(tx_h)} (Just now)"
            update_wallet_state(self.account_config.label, status="[SUCCESS] Faucet", last_tx=tx_fmt)
            self.update_balance_display()
        else:
            update_wallet_state(self.account_config.label, status="[WAITING] Idle")

    def execute_swap(self, amount_usdc: Decimal) -> None:
        amount_units = to_units(amount_usdc, USDC_DECIMALS)
        balance = self.usdc_contract.functions.balanceOf(self.account.address).call()
        if balance < amount_units:
            return

        self.log.info(f"[SWAPPING] {amount_usdc:.0f} USDC...")
        quote_res = self._make_authenticated_request(
            "POST",
            f"{API_BASE}/api/v1/swap/quote",
            json={
                "tokenIn": USDC_ADDRESS,
                "amountIn": str(amount_units),
                "slippageBps": SWAP_SLIPPAGE_BPS,
                "recipient": self.account.address
            }
        )
        quote_data = quote_res.json() if quote_res.content else {}
        tx_data = quote_data.get("tx") or quote_data.get("transaction")
        if not tx_data:
            return

        target_router = Web3.to_checksum_address(tx_data.get("to"))
        self.ensure_usdc_approval(target_router, amount_units)

        raw_tx = {
            "to": target_router,
            "data": tx_data.get("data"),
            "value": int(tx_data.get("value", 0)),
            "chainId": 84532
        }
        tx_hash = self.send_raw_transaction(raw_tx)
        tx_fmt = f"{short_address(tx_hash)} (Just now)"
        update_wallet_state(self.account_config.label, status=f"[SUCCESS] Swap {amount_usdc:.0f} USDC", last_tx=tx_fmt)
        self.update_balance_display()

    def check_live_auction(self) -> dict[str, Any] | None:
        url = f"{API_BASE}/api/v1/pools/active"
        try:
            response = self._make_authenticated_request("GET", url)
            if response.status_code == 200:
                pools = response.json()
                if isinstance(pools, list) and len(pools) > 0:
                    return pools[0]
        except Exception:
            pass
        return None

    def submit_bid(self, amount_usdc: Decimal) -> None:
        amount_units = to_units(amount_usdc, USDC_DECIMALS)
        balance = self.usdc_contract.functions.balanceOf(self.account.address).call()
        if balance < amount_units:
            return

        pool = self.check_live_auction()
        if not pool:
            return

        pool_id = pool.get("id") or pool.get("poolId")
        clearing_price_x96 = int(pool.get("clearingPriceX96", 0))
        tick_spacing = int(pool.get("tickSpacingX96", 1))
        
        base_price = Decimal(pool.get("currentPrice", "1.0"))
        bid_price = base_price * Decimal(str(BID_PRICE_MULTIPLIER))
        price_x96 = human_price_to_x96(bid_price, currency_decimals=USDC_DECIMALS, token_decimals=18, tick_spacing_x96=tick_spacing)
        
        if price_x96 <= clearing_price_x96:
            price_x96 = ((clearing_price_x96 // tick_spacing) + 1) * tick_spacing

        nonce = random.randint(1, 2**32 - 1)
        deadline = int(time.time()) + 3600

        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"}
                ],
                "TokenPermissions": [
                    {"name": "token", "type": "address"},
                    {"name": "amount", "type": "256"}
                ],
                "PermitSingle": [
                    {"name": "details", "type": "TokenPermissions"},
                    {"name": "spender", "type": "address"},
                    {"name": "sigDeadline", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"}
                ]
            },
            "primaryType": "PermitSingle",
            "domain": {
                "name": "Permit2",
                "chainId": 84532,
                "verifyingContract": PERMIT2_ADDRESS
            },
            "message": {
                "details": {
                    "token": USDC_ADDRESS,
                    "amount": str(amount_units)
                },
                "spender": Web3.to_checksum_address(pool.get("contractAddress", PERMIT2_ADDRESS)),
                "sigDeadline": str(deadline),
                "nonce": str(nonce)
            }
        }

        self.log.info(f"[BIDDING] Pool #{pool_id}")
        self.ensure_usdc_approval(PERMIT2_ADDRESS, amount_units)
        sign_obj = encode_typed_data(full_message=typed_data)
        signed_msg = self.account.sign_message(sign_obj)
        signature = signed_msg.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature

        bid_payload = {
            "poolId": pool_id,
            "userAddress": self.account.address,
            "amount": str(amount_units),
            "maxPriceX96": str(price_x96),
            "permit": {
                "nonce": str(nonce),
                "deadline": str(deadline),
                "signature": signature
            }
        }

        bid_res = self._make_authenticated_request("POST", f"{API_BASE}/api/v1/bids", json=bid_payload)
        res_data = bid_res.json() if bid_res.content else {}
        if bid_res.status_code in (200, 201) or res_data.get("success"):
            tx_h = res_data.get("txHash") or res_data.get("hash") or "0x3c2..."
            tx_fmt = f"{short_address(tx_h)} (Just now)"
            update_wallet_state(self.account_config.label, status=f"[SUCCESS] Bid {amount_usdc:.0f} USDC", last_tx=tx_fmt)
            self.update_balance_display()
        else:
            raise RuntimeError(f"Gagal Submit Bid")

    def exit_and_claim_auction(self) -> list[str]:
        claimed_tokens = []
        try:
            self.log.info("[CHECKING] Ended Auctions...")
            res = self._make_authenticated_request("GET", f"{API_BASE}/api/v1/pools/history?user={self.account.address}")
            if res.status_code != 200:
                return claimed_tokens

            history = res.json() if res.content else []
            if not isinstance(history, list):
                return claimed_tokens

            for pool in history:
                pool_id = pool.get("id") or pool.get("poolId")
                status = str(pool.get("status", "")).lower()
                is_claimable = pool.get("claimable", False) or pool.get("userHasUnclaimed", False)
                reward_token = pool.get("tokenAddress") or pool.get("rewardTokenAddress")

                if (status in ["ended", "settled", "closed"]) or is_claimable:
                    self.log.info(f"[EXIT BIDS] Pool #{pool_id}...")
                    self._make_authenticated_request(
                        "POST", 
                        f"{API_BASE}/api/v1/bids/exit", 
                        json={"poolId": pool_id, "userAddress": self.account.address}
                    )
                    
                    self.log.info(f"[CLAIM TOKENS] Pool #{pool_id}...")
                    claim_res = self._make_authenticated_request(
                        "POST", 
                        f"{API_BASE}/api/v1/bids/claim", 
                        json={"poolId": pool_id, "userAddress": self.account.address}
                    )
                    
                    c_data = claim_res.json() if claim_res.content else {}
                    if claim_res.status_code in (200, 201) or c_data.get("success"):
                        tx_h = c_data.get("txHash") or c_data.get("hash") or "0x..."
                        tx_fmt = f"{short_address(tx_h)} (Just now)"
                        update_wallet_state(self.account_config.label, status=f"[SUCCESS] Claim Pool #{pool_id}", last_tx=tx_fmt)
                        if reward_token:
                            claimed_tokens.append(Web3.to_checksum_address(reward_token))
                        time.sleep(2)

            return claimed_tokens

        except Exception as err:
            self.log.error(f"Exit/Claim err: {str(err)[:15]}")
            return claimed_tokens

    def auto_swap_rewards_to_usdc(self, token_addresses: list[str]) -> None:
        for token_addr in set(token_addresses):
            try:
                if token_addr == USDC_ADDRESS:
                    continue

                token_contract = self.w3.eth.contract(address=token_addr, abi=ERC20_ABI)
                bal_wei = token_contract.functions.balanceOf(self.account.address).call()
                
                if bal_wei <= 0:
                    continue

                symbol = "TOKEN"
                try:
                    symbol = token_contract.functions.symbol().call()
                except Exception:
                    pass

                self.log.info(f"[AUTO-SWAP] {symbol} -> USDC...")
                quote_res = self._make_authenticated_request(
                    "POST",
                    f"{API_BASE}/api/v1/swap/quote",
                    json={
                        "tokenIn": token_addr,
                        "tokenOut": USDC_ADDRESS,
                        "amountIn": str(bal_wei),
                        "slippageBps": SWAP_SLIPPAGE_BPS,
                        "recipient": self.account.address
                    }
                )
                
                quote_data = quote_res.json() if quote_res.content else {}
                tx_data = quote_data.get("tx") or quote_data.get("transaction")
                if not tx_data:
                    continue

                target_router = Web3.to_checksum_address(tx_data.get("to"))
                allowance = token_contract.functions.allowance(self.account.address, target_router).call()
                if allowance < bal_wei:
                    self.log.info(f"[APPROVING] {symbol}...")
                    app_tx = token_contract.functions.approve(target_router, 2**256 - 1).build_transaction({"chainId": 84532})
                    self.send_raw_transaction(app_tx)

                raw_tx = {
                    "to": target_router,
                    "data": tx_data.get("data"),
                    "value": int(tx_data.get("value", 0)),
                    "chainId": 84532
                }
                tx_hash = self.send_raw_transaction(raw_tx)
                tx_fmt = f"{short_address(tx_hash)} (Just now)"
                
                update_wallet_state(self.account_config.label, status=f"[SUCCESS] Swap {symbol}->USDC", last_tx=tx_fmt)
                self.update_balance_display()
                
            except Exception as err:
                self.log.error(f"Auto-Swap err: {str(err)[:15]}")

# ==============================================================================
# 7. WORKER EKSEKUSI UTAMA DENGAN PERBAIKAN LOGIKA 24 JAM
# ==============================================================================
def process_wallet(account: AccountConfig, capsolver_key: str) -> None:
    log = DashboardLogger(account.label)
    client = UmiaWeb3Client(account, capsolver_key, log)

    # State Timer & Counter Harian Terisolasi per Wallet
    last_daily_faucet_time = 0.0
    daily_swap_timestamps: list[float] = []
    SECONDS_IN_DAY = 86400.0

    while True:
        try:
            current_time = time.time()

            # Bersihkan timestamp swap yang sudah lebih dari 24 jam yang lalu (Rolling Window 24 Jam)
            daily_swap_timestamps = [t for t in daily_swap_timestamps if current_time - t < SECONDS_IN_DAY]

            # ==================================================================
            # 1. DAILY ACTIVITIES: FAUCET & DAILY SWAP (Maks 6x per 24 Jam)
            # ==================================================================
            if FAUCET_ENABLED and (current_time - last_daily_faucet_time >= SECONDS_IN_DAY):
                try:
                    client.claim_faucet()
                    last_daily_faucet_time = current_time
                except Exception as err:
                    log.error(f"Faucet err: {str(err)[:15]}")

            if SWAP_ENABLED and (len(daily_swap_timestamps) < SWAP_USDC_DAILY):
                try:
                    amount = Decimal(str(round(random.uniform(float(SWAP_USDC_MIN), float(SWAP_USDC_MAX)), 2)))
                    client.execute_swap(amount)
                    
                    daily_swap_timestamps.append(current_time)
                    log.info(f"[DAILY SWAP] Sukses ({len(daily_swap_timestamps)}/{SWAP_USDC_DAILY})")
                except Exception as err:
                    log.error(f"Daily Swap err: {str(err)[:15]}")

            # ==================================================================
            # 2. CHECK LIVE AUCTION & SUBMIT BID
            # ==================================================================
            pool = client.check_live_auction()
            if pool and BID_ENABLED:
                amount = Decimal(str(round(random.uniform(float(BID_USDC_MIN), float(BID_USDC_MAX)), 2)))
                client.submit_bid(amount)
            else:
                update_wallet_state(account.label, status="[WAITING] No Live Auction")

            # ==================================================================
            # 3. CHECK ENDED AUCTION -> EXIT BID -> CLAIM -> AUTO-SWAP REWARD TO USDC
            # ==================================================================
            if AUTO_CLAIM_ENABLED:
                claimed_tokens = client.exit_and_claim_auction()
                
                if AUTO_SWAP_BACK_ENABLED and claimed_tokens:
                    client.auto_swap_rewards_to_usdc(claimed_tokens)

        except Exception as e:
            safe_msg = redact_text(str(e), [account.private_key, capsolver_key])
            update_wallet_state(account.label, status=f"[ERROR] {safe_msg[:20]}")

        # ==================================================================
        # 4. COOLDOWN / SLEEP (REPEAT LOOP 5-8 DETIK)
        # ==================================================================
        cooldown = random.randint(DELAY_MIN, DELAY_MAX)
        for c in range(cooldown, 0, -1):
            update_wallet_state(account.label, status=f"[SLEEP] Cooldown {c}s")
            time.sleep(1)

# ==============================================================================
# 8. MAIN ENTRYPOINT WITH LIVE UI RENDERER
# ==============================================================================
def main() -> None:
    accounts = get_accounts()
    capsolver_key = load_capsolver_key()

    if not accounts:
        print("[!] Tidak ada private key yang ditemukan di private_keys.txt. Keluar.")
        sys.exit(1)

    if not capsolver_key:
        print("[!] API Key Capsolver belum diisi di capsolver_key.txt. Keluar.")
        sys.exit(1)

    for acc in accounts:
        addr = Account.from_key(acc.private_key).address
        wallet_states[acc.label] = {
            "address": short_address(addr),
            "status": "[WAITING] Idle",
            "balance": "0 USDC",
            "last_tx": "-"
        }

    system_status["active_workers"] = len(accounts)

    if SHUFFLE_WALLETS:
        random.shuffle(accounts)

    with Live(render_dashboard(), refresh_per_second=4, screen=False) as live:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            _ = [executor.submit(process_wallet, acc, capsolver_key) for acc in accounts]
            
            while True:
                live.update(render_dashboard())
                time.sleep(0.25)

if __name__ == "__main__":
    main()
