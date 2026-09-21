package sbi

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"regexp"
	"time"

	"github.com/free5gc/nef/internal/logger"
	nef_util "github.com/free5gc/nef/internal/util"
	"github.com/free5gc/openapi/models"
	"github.com/gin-gonic/gin"
)

var intentIDPattern = regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,128}$`)

// mountSCFRelay adds an experimental IUF -> NEF -> Flask intent relay.
// This endpoint is not a standardized 3GPP NEF API.
func (s *Server) mountSCFRelay() {
	authCheck := nef_util.NewRouterAuthorizationCheck(
		models.ServiceName("3gpp-traffic-influence"),
	)

	group := s.router.Group("/lab-intents/v1")
	group.Use(func(c *gin.Context) {
		authCheck.Check(c, s.Context())
	})

	group.POST("/intents", func(c *gin.Context) {
		if c.IsAborted() {
			return
		}

		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 1024*1024)
		rawBody, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "cannot read request body"})
			return
		}

		var intent map[string]json.RawMessage
		if err := json.Unmarshal(rawBody, &intent); err != nil || intent == nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "JSON object required"})
			return
		}

		var intentID string
		if err := json.Unmarshal(intent["intentId"], &intentID); err != nil ||
			!intentIDPattern.MatchString(intentID) {
			c.JSON(http.StatusBadRequest, gin.H{"error": "valid string intentId required"})
			return
		}

		randomBytes := make([]byte, 16)
		if _, err := rand.Read(randomBytes); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot generate request ID"})
			return
		}
		requestID := hex.EncodeToString(randomBytes)
		sum := sha256.Sum256(rawBody)
		bodyHash := hex.EncodeToString(sum[:])
		c.Header("X-Request-ID", requestID)

		logger.GinLog.Infof(
			"NEF_INTENT intentId=%s requestId=%s sha256=%s received",
			intentID, requestID, bodyHash,
		)

		scfURL := os.Getenv("SCF_INTENT_URL")
		relayKey := os.Getenv("SCF_RELAY_KEY")
		if scfURL == "" || len(relayKey) < 32 {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "SCF relay is not configured"})
			return
		}

		req, err := http.NewRequestWithContext(
			c.Request.Context(), http.MethodPost, scfURL, bytes.NewReader(rawBody),
		)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot create SCF request"})
			return
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Request-ID", requestID)
		req.Header.Set("X-SCF-Relay-Key", relayKey)

		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.Proxy = nil
		defer transport.CloseIdleConnections()

		client := &http.Client{
			Timeout:   10 * time.Second,
			Transport: transport,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		}

		resp, err := client.Do(req)
		if err != nil {
			logger.GinLog.Errorf(
				"NEF_INTENT intentId=%s requestId=%s SCF error=%v",
				intentID, requestID, err,
			)
			c.JSON(http.StatusBadGateway, gin.H{
				"error": "SCF connection failed", "requestId": requestID,
			})
			return
		}
		defer resp.Body.Close()

		responseBody, err := io.ReadAll(io.LimitReader(resp.Body, 1024*1024+1))
		if err != nil || len(responseBody) > 1024*1024 {
			c.JSON(http.StatusBadGateway, gin.H{"error": "invalid SCF response"})
			return
		}

		logger.GinLog.Infof(
			"NEF_INTENT intentId=%s requestId=%s scf_status=%d",
			intentID, requestID, resp.StatusCode,
		)

		contentType := resp.Header.Get("Content-Type")
		if contentType == "" {
			contentType = "application/json"
		}
		c.Data(resp.StatusCode, contentType, responseBody)
	})
}
