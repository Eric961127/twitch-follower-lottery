const updateButton = document.getElementById("updateButton");
const drawButton = document.getElementById("drawButton");
const followerCount = document.getElementById("followerCount");
const listStatus = document.getElementById("listStatus");
const winnerElement = document.getElementById("winner");
const message = document.getElementById("message");

let followers = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

updateButton.addEventListener("click", async () => {
  updateButton.disabled = true;
  drawButton.disabled = true;
  followerCount.textContent = "更新中...";
  listStatus.textContent = "讀取 Twitch 中";
  winnerElement.textContent = "等待抽獎...";
  message.textContent = "正在取得最新追蹤者名單...";

  try {
    const response = await fetch("/api/followers", { credentials: "same-origin" });
    const data = await response.json();

    if (!response.ok || !data.ok) throw new Error(data.error || "更新失敗");

    followers = data.followers;
    followerCount.textContent = `${data.count} 人`;
    listStatus.textContent = "已更新";
    message.textContent = `✅ 已成功取得 ${data.count} 位追蹤者`;
    drawButton.disabled = data.count === 0;
  } catch (error) {
    followers = [];
    followerCount.textContent = "更新失敗";
    listStatus.textContent = "錯誤";
    message.textContent = "❌ " + error.message;
  } finally {
    updateButton.disabled = false;
  }
});

drawButton.addEventListener("click", async () => {
  if (!followers.length) return;

  drawButton.disabled = true;
  updateButton.disabled = true;
  message.textContent = "🎰 抽獎中...";

  for (let i = 0; i < 28; i++) {
    const person = followers[Math.floor(Math.random() * followers.length)];
    winnerElement.textContent = person.name;
    await sleep(45 + i * 8);
  }

  try {
    const response = await fetch("/api/draw", {
      method: "POST",
      credentials: "same-origin"
    });
    const data = await response.json();

    if (!response.ok || !data.ok) throw new Error(data.error || "抽獎失敗");

    winnerElement.textContent = `🎉 ${data.winner.name} 🎉`;
    message.textContent = "🎊 抽獎完成！";
  } catch (error) {
    message.textContent = "❌ " + error.message;
  } finally {
    drawButton.disabled = false;
    updateButton.disabled = false;
  }
});
