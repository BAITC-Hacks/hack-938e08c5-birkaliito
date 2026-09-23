package domain

type Error struct { Code, Message string; Cause error }
func (e *Error) Error() string { if e.Cause!=nil{return e.Code+": "+e.Cause.Error()};return e.Code+": "+e.Message }
func (e *Error) Unwrap() error { return e.Cause }
func Err(code,message string) error {return &Error{Code:code,Message:message}}
func Wrap(code,message string,cause error) error{return &Error{Code:code,Message:message,Cause:cause}}
func Invalid(message string) error{return Err("VALIDATION_ERROR",message)}
func Violation(message string) error{return Err("UPSTREAM_CONTRACT_VIOLATION",message)}
