package integration

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"wind/backend/api"
)

func TestCommittedFixturesMatchCanonicalOpenAPI(t *testing.T) {
	v, e := api.NewValidator()
	if e != nil {
		t.Fatal(e)
	}
	dir := "../../testdata/fixtures"
	b, e := os.ReadFile(filepath.Join(dir, "manifest.json"))
	if e != nil {
		t.Fatal("generate fixtures with go run ./cmd/fixtures:", e)
	}
	var manifest map[string]string
	if e = json.Unmarshal(b, &manifest); e != nil {
		t.Fatal(e)
	}
	if len(manifest) < 30 {
		t.Fatal("missing response scenarios")
	}
	for file, schema := range manifest {
		t.Run(file, func(t *testing.T) {
			b, e := os.ReadFile(filepath.Join(dir, file))
			if e != nil {
				t.Fatal(e)
			}
			if strings.HasSuffix(schema, "[]") {
				var list []json.RawMessage
				if e = json.Unmarshal(b, &list); e != nil || list == nil {
					t.Fatal("expected array", e)
				}
				for _, item := range list {
					if e = v.Validate(strings.TrimSuffix(schema, "[]"), item); e != nil {
						t.Fatal(e)
					}
				}
			} else if e = v.Validate(schema, b); e != nil {
				t.Fatal(e)
			}
		})
	}
}
