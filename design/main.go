package main

import (
	"embed"
	"log"
	"net/http"
)

//go:embed index.html styles.css app.js model.mjs assets
var assets embed.FS

func main() {
	log.Println("AURA design prototype: http://localhost:4173")
	log.Fatal(http.ListenAndServe("127.0.0.1:4173", http.FileServer(http.FS(assets))))
}
