<?xml version="1.0" encoding="UTF-8" ?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns="http://www.w3.org/1999/xhtml" xmlns:atom="http://www.w3.org/2005/Atom">
    <xsl:output method="html" indent="yes" encoding="UTF-8"/>
    <xsl:template match="/rss/channel">
        <html>
            <head>
                <title>
                    <xsl:value-of select="title" />
                </title>
                <link rel="stylesheet" href="feed.css"/>
                <link rel="alternate" href="{link}" type="application/rss+xml" title="RSS"/>
            </head>
            <body>
                <h1><a href="{link}"><xsl:value-of select="title" /></a></h1>

                <xsl:apply-templates select="textInput" />
                <ul id="feed">
                    <xsl:apply-templates select="item" />
                </ul>
                <xsl:apply-templates select="atom:link[@rel='next']" />
            </body>
        </html>
    </xsl:template>
    <xsl:template match="atom:link[@rel='next']">
        <div style="text-align:center" id="next">
            <a  href="{@href}">Next</a>
        </div>
    </xsl:template>
    <xsl:template match="textInput">
                <form action="{link}" id="search">
                    <input type="text" name="{name}"  />
                    <input type="submit" value="{title}" />
                </form>
    </xsl:template>
    <xsl:template match="item">
        <li>
            <div class="source"><b>[<a href="{source/@url}"><xsl:value-of select="source"/></a>@<xsl:value-of select="pubDate"/>]</b>
            </div> 
            <input type="checkbox" class="more" id="{guid}"/> 
            <label for="{guid}">Read more</label> 
            <h2><a href="{link}"><xsl:value-of select="title"/></a></h2>
            <div class="description">
                <xsl:value-of select="description" disable-output-escaping="yes"/>
            </div>
            <p>
            <xsl:apply-templates select="enclosure" />
            </p>
        </li>
    </xsl:template>
    <xsl:template match="enclosure[starts-with(@type,'image')]">
        <details>
            <summary>Image Enclosure</summary>
            <a href="{@url}" target="_blank"><img style="max-width:100%;display:block;margin:auto;" loading="lazy" src="{@url}"/></a>
        </details>
    </xsl:template>
    <xsl:template match="enclosure[starts-with(@type,'video')]">
        <details>
            <summary>Video Enclosure</summary>
            <video style="max-width:100%;display:block;margin:auto;" controls="true" preload="none">
                <source src="{@url}" type="{@type}"/>
            </video>
        </details>
    </xsl:template>
    <xsl:template match="enclosure[starts-with(@type,'audio')]">
        <audio width="100%" controls="true" preload="none">
            <source src="{@url}" type="{@type}"/>
        </audio>
    </xsl:template>
    

</xsl:stylesheet>
