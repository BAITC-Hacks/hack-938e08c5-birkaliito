package architecture

import (
	"go/parser"
	"go/token"
	"io/fs"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestDependencyDirection(t *testing.T) {
	root := "../../internal"
	e := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		f, e := parser.ParseFile(token.NewFileSet(), path, nil, parser.ImportsOnly)
		if e != nil {
			return e
		}
		rel := filepath.ToSlash(path)
		for _, imp := range f.Imports {
			p, _ := strconv.Unquote(imp.Path.Value)
			if strings.Contains(rel, "/domain/") || strings.Contains(rel, "/application/") {
				for _, bad := range []string{"/transport/", "/adapters/", "gin-gonic", "database/sql", "/api", "os"} {
					if strings.Contains(p, bad) {
						t.Errorf("%s forbidden import %s", path, p)
					}
				}
			}
			if strings.Contains(rel, "/handlers/") {
				for _, bad := range []string{"/adapters/", "/ports", "/app", "database/sql", "os"} {
					if strings.Contains(p, bad) {
						t.Errorf("handler %s forbidden dependency %s", path, p)
					}
				}
			}
		}
		return nil
	})
	if e != nil {
		t.Fatal(e)
	}
}
