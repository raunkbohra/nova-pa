module.exports = {
  apps: [
    {
      name: "nova",
      script: "main.py",
      interpreter: "./venv/bin/python3",
      cwd: "/home/ubuntu/nova-pa",
      env_production: {
        NODE_ENV: "production",
      },
      watch: false,
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 10,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "logs/nova-error.log",
      out_file: "logs/nova-out.log",
      merge_logs: true,
    },
    {
      name: "nova-tunnel",
      script: "cloudflared",
      args: "tunnel --config /home/ubuntu/.cloudflared/config.yml run",
      interpreter: "none",
      watch: false,
      autorestart: true,
      restart_delay: 3000,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "logs/tunnel-error.log",
      out_file: "logs/tunnel-out.log",
    },
  ],
};
