FROM golang:1.25.6-alpine

WORKDIR /app

COPY . .

RUN go build -o aura main.go

EXPOSE 4173

CMD ["./aura"]
