static class ConnectionPage
{
    public static string Render(string csrf, bool configured, bool tokenSaved)
    {
        var action = configured
            ? $"""
              <p>Thông tin ứng dụng đã được lưu trên máy.</p>
              <form method="post" action="/connect">
                <input type="hidden" name="csrf" value="{csrf}">
                <button>Kết nối tài khoản cTrader</button>
              </form>
              <details><summary>Cập nhật thông tin ứng dụng</summary>{SetupForm(csrf)}</details>
              """
            : SetupForm(csrf);
        return $$"""
        <!doctype html>
        <html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
        <title>Kết nối FxPro cTrader</title>
        <style>
        *{box-sizing:border-box}body{margin:0;background:#10151c;color:#edf1f7;font:16px system-ui}
        main{max-width:620px;margin:7vh auto;padding:28px}h1{font-size:28px}p{color:#b7c2d0;line-height:1.6}
        label{display:block;margin:22px 0 8px}input{width:100%;padding:13px;border:1px solid #556171;border-radius:6px;background:#18212c;color:white;font:inherit}
        button{padding:14px 20px;margin:24px 0;background:#79dcc2;border:0;border-radius:6px;font:inherit;cursor:pointer}
        code{display:block;background:#18212c;padding:14px;overflow-wrap:anywhere}summary{cursor:pointer;margin-top:22px}
        a{color:#79dcc2}
        </style>
        <main><h1>Kết nối FxPro cTrader</h1>
        <p>{{(tokenSaved ? "Token OAuth đã được lưu. Bạn có thể kết nối lại để cấp quyền mới." : "Nhập thông tin ứng dụng Open API đã được duyệt để kết nối tài khoản.")}}</p>
        <p>Đăng ký Redirect URI này trong ứng dụng cTrader của bạn.</p>
        <code>http://localhost:8787/callback</code>
        {{action}}
        <p>Client Secret và token được lưu trong thư mục cấu hình riêng trên máy. Khi kết nối, cTrader sẽ hỏi bạn chọn tài khoản và cấp quyền giao dịch.</p>
        </main></html>
        """;
    }

    private static string SetupForm(string csrf) => $"""
        <form method="post" action="/setup" autocomplete="off">
          <input type="hidden" name="csrf" value="{csrf}">
          <label for="clientId">Client ID</label>
          <input id="clientId" name="clientId" required maxlength="512">
          <label for="clientSecret">Client Secret</label>
          <input id="clientSecret" name="clientSecret" type="password" required maxlength="2048" autocomplete="new-password">
          <button>Lưu thông tin ứng dụng</button>
        </form>
        """;
}
