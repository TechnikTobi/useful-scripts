# See: https://stackoverflow.com/questions/47565203/cargo-build-hangs-with-blocking-waiting-for-file-lock-on-the-registry-index-a
rm -rf ~/.cargo/registry/index/* ~/.cargo/.package-cache
