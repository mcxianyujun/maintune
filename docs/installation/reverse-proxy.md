# 反向代理

Caddy 示例：

```caddyfile
maintainer.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
```

代理必须保留请求体和 `X-GitHub-*` 头，不能缓存 `/api/*` 或 `/webhooks/github`。`index.html` 不应长期缓存；哈希静态资源可以长期缓存。部署后使用全新浏览器上下文验证登录控件实际可见。
