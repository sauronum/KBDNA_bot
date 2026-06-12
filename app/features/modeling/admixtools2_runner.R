#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(jsonlite)
  library(admixtools)
})

json_error <- function(message, code = "backend_error", details = list()) {
  list(status = "error", errors = list(list(code = code, message = message, details = details)), result = NULL)
}

emit <- function(payload) {
  cat(jsonlite::toJSON(payload, auto_unbox = TRUE, null = "null", na = "null", digits = 16), "\n", sep = "")
}

scalar <- function(value, default = NULL) {
  if (is.null(value) || length(value) < 1) return(default)
  text <- trimws(as.character(value[[1]]))
  if (!nzchar(text)) return(default)
  text
}

bool <- function(value, default = FALSE) {
  if (is.null(value) || length(value) < 1) return(default)
  if (is.logical(value[[1]])) return(isTRUE(value[[1]]))
  text <- tolower(trimws(as.character(value[[1]])))
  if (text %in% c("1", "true", "yes", "y", "on")) return(TRUE)
  if (text %in% c("0", "false", "no", "n", "off")) return(FALSE)
  default
}

num <- function(value, default = NULL) {
  if (is.null(value) || length(value) < 1) return(default)
  out <- suppressWarnings(as.numeric(value[[1]]))
  if (is.na(out)) return(default)
  out
}

request_path <- function(args) {
  for (index in seq_along(args)) {
    item <- args[[index]]
    if (item %in% c("--request", "-r") && index < length(args)) return(args[[index + 1]])
    if (startsWith(item, "--request=")) return(substring(item, nchar("--request=") + 1))
  }
  NULL
}

as_chars <- function(value) {
  if (is.null(value)) return(character())
  unique(as.character(unlist(value, use.names = FALSE)))
}

cache_key <- function(geno_prefix, pops, options) {
  payload <- list(
    geno_prefix = geno_prefix,
    pops = sort(unique(pops)),
    blgsize = num(options$blgsize, 0.05),
    auto_only = bool(options$auto_only, TRUE),
    transitions = bool(options$transitions, TRUE),
    transversions = bool(options$transversions, TRUE),
    adjust_pseudohaploid = bool(options$adjust_pseudohaploid, TRUE),
    maxmiss = num(options$maxmiss, 0),
    minmaf = num(options$minmaf, 0),
    maxmaf = num(options$maxmaf, 0.5)
  )
  if (requireNamespace("digest", quietly = TRUE)) return(digest::digest(payload, algo = "sha1"))
  gsub("[^A-Za-z0-9_.-]+", "_", paste(sort(unique(pops)), collapse = "__"))
}

ensure_f2_cache <- function(geno_prefix, cache_root, pops, options) {
  if (is.null(cache_root)) return(NULL)
  dir.create(cache_root, recursive = TRUE, showWarnings = FALSE)
  key <- cache_key(geno_prefix, pops, options)
  cache_dir <- file.path(cache_root, paste0("f2_", key))
  metadata <- file.path(cache_dir, "cache_metadata.json")
  status <- "hit"
  if (!file.exists(metadata)) {
    lock_dir <- paste0(cache_dir, ".lock")
    acquired <- FALSE
    for (attempt in seq_len(300)) {
      if (dir.create(lock_dir, recursive = TRUE, showWarnings = FALSE)) {
        acquired <- TRUE
        break
      }
      if (file.exists(metadata)) break
      Sys.sleep(1)
    }
    if (!file.exists(metadata)) {
      if (!acquired) stop("Timed out waiting for f2 cache lock: ", cache_dir, call. = FALSE)
      on.exit(unlink(lock_dir, recursive = TRUE, force = TRUE), add = TRUE)
      dir.create(cache_dir, recursive = TRUE, showWarnings = FALSE)
      extract_args <- list(
        pref = geno_prefix,
        outdir = cache_dir,
        pops = unique(pops),
        blgsize = num(options$blgsize, 0.05),
        maxmiss = num(options$maxmiss, 0),
        minmaf = num(options$minmaf, 0),
        maxmaf = num(options$maxmaf, 0.5),
        transitions = bool(options$transitions, TRUE),
        transversions = bool(options$transversions, TRUE),
        auto_only = bool(options$auto_only, TRUE),
        adjust_pseudohaploid = bool(options$adjust_pseudohaploid, TRUE),
        overwrite = TRUE,
        verbose = FALSE
      )
      do.call(admixtools::extract_f2, extract_args)
      status <- "created"
    } else {
      status <- "hit_after_wait"
    }
  }
  list(path = cache_dir, key = key, status = status)
}

data_source <- function(request, pops) {
  files <- request$dataset_files
  options <- request$options
  if (is.null(options)) options <- list()
  f2_dir <- scalar(files$f2_dir, scalar(files$f2, NULL))
  f2_cache_dir <- scalar(files$f2_cache_dir, scalar(files$f2_cache, NULL))
  geno_prefix <- scalar(files$geno_prefix, NULL)
  afprod <- bool(options$afprod, FALSE)
  if (!is.null(f2_dir)) {
    return(list(data = admixtools::f2_from_precomp(f2_dir, pops = unique(pops), afprod = afprod, verbose = FALSE), source = list(type = "precomputed_f2", path = f2_dir)))
  }
  if (!is.null(geno_prefix) && !is.null(f2_cache_dir)) {
    cache <- ensure_f2_cache(geno_prefix, f2_cache_dir, unique(pops), options)
    return(list(data = admixtools::f2_from_precomp(cache$path, pops = unique(pops), afprod = afprod, verbose = FALSE), source = list(type = "precomputed_f2_cache", path = cache$path, cache_status = cache$status, cache_key = cache$key)))
  }
  if (!is.null(geno_prefix)) {
    return(list(data = geno_prefix, source = list(type = "genotype_prefix", path = geno_prefix)))
  }
  stop("dataset_files must provide f2_dir or geno_prefix", call. = FALSE)
}

rows_from_frame <- function(frame) {
  frame <- as.data.frame(frame)
  if (nrow(frame) < 1) return(list())
  lapply(seq_len(nrow(frame)), function(index) as.list(frame[index, , drop = FALSE]))
}

normalize_qpwave <- function(value) {
  frame <- as.data.frame(value)
  names_lower <- tolower(names(frame))
  pick <- function(candidates) {
    match <- match(candidates, names_lower, nomatch = 0)
    if (any(match > 0)) names(frame)[match[match > 0][[1]]] else NULL
  }
  rank_col <- pick(c("f4rank", "rank"))
  dof_col <- pick(c("dof"))
  chisq_col <- pick(c("chisq", "chisqdiff"))
  p_col <- pick(c("p", "pvalue", "p_value", "tail"))
  rows <- list()
  if (nrow(frame) < 1) return(rows)
  for (index in seq_len(nrow(frame))) {
    rows[[index]] <- list(
      rank = if (!is.null(rank_col)) frame[[rank_col]][[index]] else index - 1,
      dof = if (!is.null(dof_col)) frame[[dof_col]][[index]] else NA,
      chisq = if (!is.null(chisq_col)) frame[[chisq_col]][[index]] else NA,
      tail = if (!is.null(p_col)) frame[[p_col]][[index]] else NA
    )
  }
  rows
}

run_qpwave <- function(request) {
  left <- as_chars(request$left)
  right <- as_chars(request$right)
  pops <- unique(c(left, right))
  source <- data_source(request, pops)
  options <- request$options
  if (is.null(options)) options <- list()
  captured <- character()
  result <- withCallingHandlers(
    admixtools::qpwave(
      source$data,
      left = left,
      right = right,
      fudge = num(options$fudge, 1e-04),
      auto_only = bool(options$auto_only, TRUE),
      blgsize = num(options$blgsize, 0.05),
      poly_only = bool(options$poly_only, FALSE),
      boot = bool(options$boot, FALSE),
      constrained = bool(options$constrained, FALSE),
      cpp = bool(options$cpp, TRUE),
      verbose = FALSE
    ),
    message = function(message) {
      captured <<- c(captured, conditionMessage(message))
      invokeRestart("muffleMessage")
    },
    warning = function(warning) {
      captured <<- c(captured, conditionMessage(warning))
      invokeRestart("muffleWarning")
    }
  )
  list(status = "completed", warnings = as.list(captured), result = list(ranks = normalize_qpwave(result), rows = rows_from_frame(result), data_source = source$source))
}

run_fstats <- function(request) {
  stat <- scalar(request$statistic, "f4")
  pops <- as_chars(request$populations)
  source <- data_source(request, pops)
  options <- request$options
  if (is.null(options)) options <- list()
  boot <- bool(options$boot, TRUE)
  result <- switch(
    stat,
    f2 = admixtools::f2(source$data, pop1 = pops[[1]], pop2 = pops[[2]], boot = boot, verbose = FALSE),
    f3 = admixtools::f3(source$data, pop1 = pops[[1]], pop2 = pops[[2]], pop3 = pops[[3]], boot = boot, verbose = FALSE),
    f4 = admixtools::f4(source$data, pop1 = pops[[1]], pop2 = pops[[2]], pop3 = pops[[3]], pop4 = pops[[4]], boot = boot, verbose = FALSE),
    stop("Unsupported statistic: ", stat, call. = FALSE)
  )
  list(status = "completed", warnings = list(), result = list(statistic = stat, rows = rows_from_frame(result), data_source = source$source))
}

main <- function() {
  path <- request_path(commandArgs(trailingOnly = TRUE))
  if (is.null(path)) {
    emit(json_error("--request is required", "request_missing"))
    return(invisible(1))
  }
  request <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  command <- scalar(request$command, "")
  payload <- tryCatch(
    {
      if (identical(command, "qpwave")) run_qpwave(request)
      else if (identical(command, "fstats")) run_fstats(request)
      else json_error(paste("Unsupported command:", command), "unsupported_command")
    },
    error = function(exc) json_error(conditionMessage(exc), "runner_failed")
  )
  payload$command <- command
  payload$engine <- "admixtools2"
  emit(payload)
}

main()
