package main

import (
	"embed"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
)

//go:embed index.html styles.css app.js model.mjs api.mjs assets
var assets embed.FS

func main() {
	backendURL := os.Getenv("BACKEND_URL")
	if backendURL == "" {
		backendURL = "http://127.0.0.1:8080"
	}
	backend, err := url.Parse(backendURL)
	if err != nil {
		log.Fatal(err)
	}
	proxy := httputil.NewSingleHostReverseProxy(backend)
	mux := http.NewServeMux()
	for _, path := range []string{"/api/", "/healthz", "/readyz", "/docs", "/openapi.yaml"} {
		mux.Handle(path, proxy)
	}
	mux.Handle("/", http.FileServer(http.FS(assets)))
	
	addr := os.Getenv("HTTP_ADDR")
	if addr == "" {
		addr = "127.0.0.1:4173"
	}
	log.Printf("AURA: http://%s (backend proxy: %s)\n", addr, backendURL)
	log.Fatal(http.ListenAndServe(addr, mux))
}
