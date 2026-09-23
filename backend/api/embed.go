package api

import (
 "bytes"
 _ "embed"
 "encoding/json"
 "fmt"
 "io"
 "github.com/santhosh-tekuri/jsonschema/v6"
)

// Spec is JSON-formatted YAML 1.2, consumed unchanged by validator and offline viewer.
//go:embed openapi.yaml
var Spec []byte

//go:embed docs.html
var Docs []byte

type Validator struct { schemas map[string]*jsonschema.Schema }
func NewValidator() (*Validator,error) {
 var doc map[string]any
 if err:=json.Unmarshal(Spec,&doc);err!=nil{return nil,err}
 c:=jsonschema.NewCompiler();c.AssertFormat()
 if err:=c.AddResource("urn:wind:contract",doc);err!=nil{return nil,err}
 v:=&Validator{schemas:make(map[string]*jsonschema.Schema)}
 for name:=range doc["components"].(map[string]any)["schemas"].(map[string]any){
  s,err:=c.Compile("urn:wind:contract#/components/schemas/"+name);if err!=nil{return nil,err};v.schemas[name]=s
 }
 return v,nil
}
func (v *Validator) Validate(name string,b []byte) error {
 s,ok:=v.schemas[name];if !ok{return fmt.Errorf("unknown contract %s",name)}
 var value any;d:=json.NewDecoder(bytes.NewReader(b));d.UseNumber()
 if err:=d.Decode(&value);err!=nil{return err}
 if err:=d.Decode(new(any));err!=io.EOF{return fmt.Errorf("trailing JSON")}
 return s.Validate(value)
}
