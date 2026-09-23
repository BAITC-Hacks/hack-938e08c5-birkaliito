package ports

import "context"

type requestIDKey struct{}

// Only request metadata travels in context; dependencies are constructor arguments.
func WithRequestID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, requestIDKey{}, id)
}
func RequestID(ctx context.Context) string { v, _ := ctx.Value(requestIDKey{}).(string); return v }
