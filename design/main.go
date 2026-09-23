package main

import (
	"embed"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
)

//go:embed index.html styles.css app.js model.mjs api.mjs assets
var assets embed.FS

func main() {
	backend, err := url.Parse("http://127.0.0.1:8080")
	if err != nil {
		log.Fatal(err)
	}
	proxy := httputil.NewSingleHostReverseProxy(backend)
	mux := http.NewServeMux()
	for _, path := range []string{"/api/", "/healthz", "/readyz", "/docs", "/openapi.yaml"} {
		mux.Handle(path, proxy)
	}
	mux.Handle("/", http.FileServer(http.FS(assets)))
	log.Println("AURA: http://localhost:4173 (backend proxy: http://127.0.0.1:8080)")
	log.Fatal(http.ListenAndServe("127.0.0.1:4173", mux))
}
