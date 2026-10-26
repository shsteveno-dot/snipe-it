module snipeit-distroless-entrypoint

go 1.26.10

// Keep the process model of the go 1.22 baseline: the Go 1.25 runtime would otherwise hold a
// descriptor on the cgroup CPU limit and resize GOMAXPROCS while init and the supervisor run.
godebug (
	containermaxprocs=0
	updatemaxprocs=0
)
