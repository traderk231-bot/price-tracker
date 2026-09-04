Price Monitor(Amazon.ca + Walmart.ca)

追蹤你張list入面嘅日用品,跌到你set嘅target price就send Telegram通知, 同一件產品喺Amazon/Walmart有比較,會highlight邊個平台平過target。

目錄結構
price-monitor/
├── products.json                      # 你嘅產品清單(可以自己編輯)
├── price_history.json                 # 每次run完自動更新,唔使手動改
├── scraper.py                         # 主程式
├── requirements.txt
└── .github/workflows/price-check.yml  # 每日自動觸發嘅設定
第一步:開GitHub repo(免費,唔使信用卡)
去 github.com 開個免費帳戶(得email)
開一個新嘅 private repo,例如叫 price-monitor
將呢個資料夾成個上傳(或者用 git push)
第二步:開Telegram Bot
Telegram度搜 @BotFather,傳 /newbot,跟住個指示改個名
BotFather會俾返你一串 bot token(例如 123456:ABC-xxxx)記低
用你自己個Telegram搵返個新bot,撳 /start(唔咁做bot會send唔到訊息俾你)
攞你嘅 chat id:瀏覽器開 https://api.telegram.org/bot<你嘅token>/getUpdates, 啱啱/start完個result入面揾 "chat":{"id": 123456789} 嗰個數字就係
第三步:喺GitHub repo入面set secrets

Repo入面 → Settings → Secrets and variables → Actions → New repository secret, 加兩條:

Name	Value
TELEGRAM_BOT_TOKEN	你喺BotFather攞到嘅token
TELEGRAM_CHAT_ID	你嘅chat id
第四步:手動test一次

Repo入面 → Actions → 揀 "Daily Price Check" → 撳 "Run workflow" 手動觸發, 睇下log同埋Telegram有冇收到訊息。跑得掂就會每日自動跑。

而家嘅產品清單狀態
✅ 13件產品已經set好,scraper會直接攞Amazon.ca / Walmart.ca嘅價
⏸️ 2件Shoppers Drug Mart產品暫時 active: false:
Barebells (Shoppers):唔知包裝幾多條,要你confirm先可以做啱嘅單價比較
Cetaphil Shea Butter Lotion (Shoppers):原本sheet入面條link連錯咗去Barebells搜尋page,要你自己搵返正確product page link
Shoppers嘅爬蟲邏輯(selector)遲啲先加,而家個架構已經預留咗位
想加新產品?

打開 products.json,copy一份已有嘅item,改返 id(要unique)、name、 platform、url、target_price、typical_price。想同另一件現有產品擺埋一齊 比較,就set返同一個 product_group。

維護提示
Amazon.ca / Walmart.ca 不時會改版面,如果收到「⚠️ 攞唔到價錢」嘅Telegram 訊息,即係個網頁結構變咗,要去揭返個product page嘅HTML,update scraper.py 入面 PLATFORM_SELECTORS 嗰段。
Cron time set喺UTC,而家係 0 13 * * *(多倫多冬令9am/夏令9am,如果想準過啲 可以自己再調)。
呢個script淨係為你自己個人用途,check頻率set做一日一次,冇打算大規模掃描, 用嘅時候都建議keep住呢個頻率,唔好調得太密。
