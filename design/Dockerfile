FROM golang:1.25.6-alpine

WORKDIR /app

COPY . .

RUN go mod init aura && go mod tidy && go build -o aura .

EXPOSE 4173

CMD ["./aura"]
