# 🚀 UMIA Finance Auto Bot

Setelah dijalankan, bot akan bekerja secara otomatis dengan alur (*flowchart*) berikut:

```text
1. [Login]                ──► Berhasil dapat JWT Token

# loop daily:

2. [(Optional) Faucet]    ──► Skipped (Kondisi acak tidak terpenuhi)

3. [(Optional) Swap]      ──► EKSEKUSI DAILY SWAP (Diacak dapat $5 USDC -> Swap USDC to Token)

#loop 5-8 detik

4. [Check Live Auction]   ──► Ada Pool #101 Aktif

5. [Submit Bid]           ──► Bid 10 USDC ke Pool #103

6. [Check Ended Auction]  ──► Menemukan Pool #102 Selesai

7. [Exit Bid]             ──► Sukses Exit Bid

8. [Claim Reward]         ──► Sukses Claim 100 FNDR

9. [Swap Reward -> USDC]  ──► Swap 100 FNDR -> 25 USDC (Auto Liquidate)

10. [Cooldown]            ──► Tidur 5 - 8 detik ──► Repeat Loop 
```


