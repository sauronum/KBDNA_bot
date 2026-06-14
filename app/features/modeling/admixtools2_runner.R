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

field <- function(value, name, default = NULL) {
  if (is.null(value) || is.null(names(value)) || !(name %in% names(value))) return(default)
  value[[name]]
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
    schema = "admixtools2_block_lengths_v1",
    admixtools_version = as.character(utils::packageVersion("admixtools")),
    geno_prefix = geno_prefix,
    pops = sort(unique(pops)),
    blgsize = num(field(options, "blgsize"), 0.05),
    auto_only = bool(field(options, "auto_only"), TRUE),
    afprod = bool(field(options, "afprod"), TRUE),
    transitions = bool(field(options, "transitions"), TRUE),
    transversions = bool(field(options, "transversions"), TRUE),
    adjust_pseudohaploid = bool(field(options, "adjust_pseudohaploid"), TRUE),
    maxmiss = num(field(options, "maxmiss"), 0),
    minmaf = num(field(options, "minmaf"), 0),
    maxmaf = num(field(options, "maxmaf"), 0.5)
  )
  if (requireNamespace("digest", quietly = TRUE)) return(digest::digest(payload, algo = "sha1"))
  gsub("[^A-Za-z0-9_.-]+", "_", paste(sort(unique(pops)), collapse = "__"))
}

cache_ready <- function(path) {
  dir.exists(path) && (
    file.exists(file.path(path, "block_lengths")) ||
    file.exists(file.path(path, "block_lengths_f2.rds")) ||
    file.exists(file.path(path, "block_lengths_ap.rds")) ||
    file.exists(file.path(path, "block_lengths_fst.rds"))
  )
}

ensure_f2_cache <- function(geno_prefix, cache_root, pops, options) {
  if (is.null(cache_root)) return(NULL)
  dir.create(cache_root, recursive = TRUE, showWarnings = FALSE)
  key <- cache_key(geno_prefix, pops, options)
  cache_dir <- file.path(cache_root, paste0("f2_", key))
  status <- "hit"
  if (!cache_ready(cache_dir)) {
    lock_dir <- paste0(cache_dir, ".lock")
    acquired <- FALSE
    for (attempt in seq_len(300)) {
      if (dir.create(lock_dir, recursive = TRUE, showWarnings = FALSE)) {
        acquired <- TRUE
        break
      }
      if (cache_ready(cache_dir)) break
      Sys.sleep(1)
    }
    if (!cache_ready(cache_dir)) {
      if (!acquired) stop("Timed out waiting for f2 cache lock: ", cache_dir, call. = FALSE)
      on.exit(unlink(lock_dir, recursive = TRUE, force = TRUE), add = TRUE)
      tmp_dir <- paste0(cache_dir, ".tmp.", Sys.getpid())
      unlink(tmp_dir, recursive = TRUE, force = TRUE)
      dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)
      on.exit(unlink(tmp_dir, recursive = TRUE, force = TRUE), add = TRUE)
      extract_args <- list(
        pref = geno_prefix,
        outdir = tmp_dir,
        pops = unique(pops),
        blgsize = num(field(options, "blgsize"), 0.05),
        maxmiss = num(field(options, "maxmiss"), 0),
        minmaf = num(field(options, "minmaf"), 0),
        maxmaf = num(field(options, "maxmaf"), 0.5),
        transitions = bool(field(options, "transitions"), TRUE),
        transversions = bool(field(options, "transversions"), TRUE),
        auto_only = bool(field(options, "auto_only"), TRUE),
        afprod = bool(field(options, "afprod"), TRUE),
        adjust_pseudohaploid = bool(field(options, "adjust_pseudohaploid"), TRUE),
        overwrite = TRUE,
        verbose = FALSE
      )
      do.call(admixtools::extract_f2, extract_args)
      if (!cache_ready(tmp_dir)) {
        stop("extract_f2 finished but did not create block_lengths in: ", tmp_dir, call. = FALSE)
      }
      unlink(cache_dir, recursive = TRUE, force = TRUE)
      if (!file.rename(tmp_dir, cache_dir)) {
        stop("Could not move rebuilt f2 cache into place: ", cache_dir, call. = FALSE)
      }
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
  f2_dir <- scalar(field(files, "f2_dir"), scalar(field(files, "f2"), NULL))
  f2_cache_dir <- scalar(field(files, "f2_cache_dir"), scalar(field(files, "f2_cache"), NULL))
  geno_prefix <- scalar(field(files, "geno_prefix"), NULL)
  afprod <- bool(field(options, "afprod"), TRUE)
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

simple_graph_edges <- function(graph_text) {
  lines <- trimws(unlist(strsplit(graph_text, "\n", fixed = TRUE), use.names = FALSE))
  lines <- lines[nzchar(lines) & !startsWith(lines, "#")]
  if (length(lines) < 1) return(NULL)
  tokens <- strsplit(lines, "\\s+")
  is_simple_edge <- vapply(tokens, function(parts) length(parts) == 3 && parts[[1]] %in% c("edge", "ledge", "redge"), logical(1))
  if (!all(is_simple_edge)) return(NULL)
  data.frame(
    from = vapply(tokens, function(parts) parts[[2]], character(1)),
    to = vapply(tokens, function(parts) parts[[3]], character(1)),
    stringsAsFactors = FALSE
  )
}

normalize_qpwave <- function(value) {
  frame <- as.data.frame(field(value, "rankdrop", value))
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

graph_edges_from_request <- function(request) {
  graph_text <- scalar(request$graph_text, NULL)
  graph_file <- scalar(request$graph_file, NULL)
  if (!is.null(graph_text)) {
    simple_edges <- simple_graph_edges(graph_text)
    if (!is.null(simple_edges)) return(simple_edges)
    graph_file <- tempfile(pattern = "kbdna_qpgraph_", fileext = ".graph")
    writeLines(graph_text, graph_file, useBytes = TRUE)
  }
  if (!is.null(graph_file)) {
    return(admixtools::parse_qpgraph_graphfile(graph_file))
  }
  edges <- field(request, "graph_edges")
  if (!is.null(edges)) {
    if (is.list(edges) && length(edges) > 0 && all(vapply(edges, is.list, logical(1)))) {
      frame <- do.call(rbind, lapply(edges, function(row) as.data.frame(row, stringsAsFactors = FALSE)))
    } else {
      frame <- as.data.frame(edges, stringsAsFactors = FALSE)
    }
    if (!all(c("from", "to") %in% names(frame)) && ncol(frame) >= 2) {
      names(frame)[1:2] <- c("from", "to")
    }
    if (all(c("from", "to") %in% names(frame))) return(frame)
  }
  stop("qpGraph request must provide graph_text, graph_file, or graph_edges", call. = FALSE)
}

graph_leaf_pops <- function(edges) {
  frame <- as.data.frame(edges, stringsAsFactors = FALSE)
  if (!all(c("from", "to") %in% names(frame)) && ncol(frame) >= 2) {
    names(frame)[1:2] <- c("from", "to")
  }
  if (!all(c("from", "to") %in% names(frame))) {
    stop("qpGraph edges must have from/to columns", call. = FALSE)
  }
  leaves <- setdiff(as.character(frame$to), as.character(frame$from))
  unique(leaves[nzchar(leaves)])
}

normalize_qpgraph <- function(value) {
  result <- list(
    score = field(value, "score"),
    worst_residual = field(value, "worst_residual"),
    p_value = field(value, "p.value"),
    edges = rows_from_frame(field(value, "edges", data.frame())),
    f3 = rows_from_frame(field(value, "f3", data.frame()))
  )
  result
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
      fudge = num(field(options, "fudge"), 1e-04),
      auto_only = bool(field(options, "auto_only"), TRUE),
      blgsize = num(field(options, "blgsize"), 0.05),
      poly_only = bool(field(options, "poly_only"), FALSE),
      boot = bool(field(options, "boot"), FALSE),
      constrained = bool(field(options, "constrained"), FALSE),
      cpp = bool(field(options, "cpp"), TRUE),
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
  rank_rows <- field(result, "rankdrop", result)
  f4_rows <- field(result, "f4", data.frame())
  list(status = "completed", warnings = as.list(captured), result = list(ranks = normalize_qpwave(result), rows = rows_from_frame(rank_rows), f4 = rows_from_frame(f4_rows), data_source = source$source))
}

run_qpgraph <- function(request) {
  edges <- graph_edges_from_request(request)
  pops <- graph_leaf_pops(edges)
  if (length(pops) < 3) stop("qpGraph requires at least 3 sampled leaf populations", call. = FALSE)
  options <- request$options
  if (is.null(options)) options <- list()
  options$afprod <- FALSE
  source <- data_source(request, pops)
  return_fstats <- scalar(field(options, "return_fstats"), "f3")
  if (tolower(return_fstats) %in% c("0", "false", "no", "none")) return_fstats <- FALSE
  captured <- character()
  result <- withCallingHandlers(
    admixtools::qpgraph(
      source$data,
      graph = edges,
      lambdascale = num(field(options, "lambdascale"), 1),
      boot = bool(field(options, "boot"), FALSE),
      diag = num(field(options, "diag"), 1e-04),
      diag_f3 = num(field(options, "diag_f3"), 1e-05),
      lsqmode = bool(field(options, "lsqmode"), FALSE),
      numstart = as.integer(num(field(options, "numstart"), 10)),
      seed = num(field(options, "seed"), NULL),
      cpp = bool(field(options, "cpp"), TRUE),
      return_fstats = return_fstats,
      return_pvalue = bool(field(options, "return_pvalue"), FALSE),
      constrained = bool(field(options, "constrained"), TRUE),
      allsnps = bool(field(options, "allsnps"), FALSE),
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
  list(status = "completed", warnings = as.list(captured), result = c(normalize_qpgraph(result), list(leaf_populations = as.list(pops), data_source = source$source)))
}

run_fstats <- function(request) {
  stat <- scalar(request$statistic, "f4")
  pops <- as_chars(request$populations)
  source <- data_source(request, pops)
  options <- request$options
  if (is.null(options)) options <- list()
  boot <- bool(field(options, "boot"), TRUE)
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
      else if (identical(command, "qpgraph")) run_qpgraph(request)
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
